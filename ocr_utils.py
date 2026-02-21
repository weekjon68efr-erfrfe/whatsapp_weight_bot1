"""
Модуль для распознавания веса с фотографий весов используя Tesseract OCR
Более легкая альтернатива EasyOCR для работы на Railway
"""
import pytesseract
import cv2
import numpy as np
import re
import os
from typing import Tuple, Optional, List, Dict
import logging

logger = logging.getLogger(__name__)

# Путь к tesseract (для Railway и локальной установки)
try:
    # Для Linux на Railway
    pytesseract.pytesseract.pytesseract_cmd = '/usr/bin/tesseract'
except:
    pass


def correct_image_orientation(image: np.ndarray) -> np.ndarray:
    """
    Попытаться исправить ориентацию изображения
    Проверяет были ли достаточно цифр распознано, если нет - пробует повернуть
    
    Args:
        image: исходное изображение
        
    Returns:
        Оптимально ориентированное изображение
    """
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    
    best_image = image.copy()
    best_count = 0
    best_angle = 0
    
    # Пробуем разные углы поворота
    for angle in [0, 90, 180, 270]:
        try:
            rotated = imutils_rotate_bound(image, angle)
            rotated_gray = cv2.cvtColor(rotated, cv2.COLOR_BGR2GRAY)
            
            # Быстрое распознавание для проверки
            try:
                text = pytesseract.image_to_string(rotated_gray, lang='rus+eng')
                if text is None or not isinstance(text, str):
                    text = ""
                
                # Считаем количество цифр
                digit_count = sum(1 for c in text if c.isdigit())
                
                if digit_count > best_count:
                    best_count = digit_count
                    best_image = rotated
                    best_angle = angle
            except Exception as e:
                logger.debug(f"Ошибка распознавания при углу {angle}: {e}")
                pass
        except Exception as e:
            logger.debug(f"Ошибка поворота {angle}: {e}")
            pass
    
    if best_angle != 0:
        logger.info(f"   🔄 Изображение повернуто на {best_angle}° для лучшего распознавания")
    
    return best_image


def imutils_rotate_bound(image: np.ndarray, angle: float) -> np.ndarray:
    """
    Повернуть изображение вокруг центра на заданный угол
    
    Args:
        image: исходное изображение
        angle: угол поворота в градусах
        
    Returns:
        Повернутое изображение
    """
    h, w = image.shape[:2]
    cx, cy = w // 2, h // 2
    
    M = cv2.getRotationMatrix2D((cx, cy), angle, 1.0)
    
    cos = np.abs(M[0, 0])
    sin = np.abs(M[0, 1])
    
    new_w = int((h * sin) + (w * cos))
    new_h = int((h * cos) + (w * sin))
    
    M[0, 2] += (new_w / 2) - cx
    M[1, 2] += (new_h / 2) - cy
    
    rotated = cv2.warpAffine(image, M, (new_w, new_h), 
                             borderMode=cv2.BORDER_REPLICATE)
    return rotated


def preprocess_image(image: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """
    Предварительная обработка изображения для улучшения распознавания текста
    Возвращает несколько вариантов обработки для максимальной надежности
    
    Args:
        image: исходное изображение
        
    Returns:
        Кортеж (основной_вариант, альтернативный_вариант)
    """
    # Конвертируем в grayscale
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    
    # Способ 1: CLAHE + Otsu (для светлого фона с темным текстом)
    clahe = cv2.createCLAHE(clipLimit=4.0, tileGridSize=(8, 8))
    contrast_enhanced = clahe.apply(gray)
    
    # Пороговое значение через Otsu
    _, binary_otsu = cv2.threshold(contrast_enhanced, 0, 255, 
                                   cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    
    # Морфологические операции
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
    primary = cv2.morphologyEx(binary_otsu, cv2.MORPH_OPEN, kernel, iterations=1)
    primary = cv2.morphologyEx(primary, cv2.MORPH_CLOSE, kernel, iterations=1)
    
    # Способ 2: Адаптивная бинаризация (более агрессивная)
    # Хороша для неравномерного освещения
    binary_adaptive = cv2.adaptiveThreshold(contrast_enhanced, 255, 
                                            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                            cv2.THRESH_BINARY, 11, 2)
    kernel2 = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    secondary = cv2.morphologyEx(binary_adaptive, cv2.MORPH_OPEN, kernel2)
    
    return primary, secondary


def extract_weight_from_image(image_path: str) -> Tuple[Optional[float], str, Dict]:
    """
    Распознать вес с фотографии весов используя Tesseract OCR
    
    Args:
        image_path: путь к файлу с изображением весов
        
    Returns:
        Кортеж (вес_в_кг, сообщение_статуса, детали_распознавания)
    """
    details = {
        'recognized_text': '',
        'confidence': 0.0,
        'method': '',
        'candidates': [],
        'error': None,
        'attempts': []
    }
    
    try:
        # Проверяем, что файл существует
        if not os.path.exists(image_path):
            details['error'] = f"Файл не найден: {image_path}"
            return None, f"❌ {details['error']}", details
        
        # Читаем изображение
        image = cv2.imread(image_path)
        if image is None:
            details['error'] = "Не удалось прочитать изображение"
            return None, f"❌ {details['error']}", details
        
        logger.info(f"🔍 Распознавание веса из изображения: {image_path}")
        logger.info(f"   Размер изображения: {image.shape}")
        
        # Попытаемся исправить ориентацию
        image = correct_image_orientation(image)
        logger.info(f"   ✓ Ориентация исправлена")
        
        # Предварительная обработка - получаем двавариант
        processed_primary, processed_secondary = preprocess_image(image)
        logger.info(f"   ✓ Изображение обработано (2 варианта)")
        
        # Пытаемся распознать с первым вариантом обработки
        logger.info(f"   Попытка 1: основной метод обработки")
        try:
            text_primary = pytesseract.image_to_string(processed_primary, lang='rus+eng')
            if text_primary is None or not isinstance(text_primary, str):
                text_primary = ""
        except Exception as e:
            logger.warning(f"   Ошибка при распознавании (попытка 1): {e}")
            text_primary = ""
        
        if text_primary:
            weight, method, candidates = extract_weight_value_advanced(text_primary)
            details['attempts'].append({'method': 'primary', 'weight': weight, 'text': text_primary})
            
            if weight is not None:
                details['method'] = method
                details['candidates'] = candidates
                details['confidence'] = 0.85
                details['recognized_text'] = text_primary
                logger.info(f"✅ Вес распознан (попытка 1): {weight} кг")
                return weight, f"✅ Вес распознан: {weight:.0f} кг", details
        
        # Если не совпало - пробуем второй вариант обработки
        logger.info(f"   Попытка 2: альтернативный метод обработки")
        try:
            text_secondary = pytesseract.image_to_string(processed_secondary, lang='rus+eng')
            if text_secondary is None or not isinstance(text_secondary, str):
                text_secondary = ""
        except Exception as e:
            logger.warning(f"   Ошибка при распознавании (попытка 2): {e}")
            text_secondary = ""
        
        if text_secondary:
            weight, method, candidates = extract_weight_value_advanced(text_secondary)
            details['attempts'].append({'method': 'secondary', 'weight': weight, 'text': text_secondary})
            
            if weight is not None:
                details['method'] = method
                details['candidates'] = candidates
                details['confidence'] = 0.75
                details['recognized_text'] = text_secondary
                logger.info(f"✅ Вес распознан (попытка 2): {weight} кг")
                return weight, f"✅ Вес распознан: {weight:.0f} кг", details
        
        # Если оба варианта не сработали
        all_text = (text_primary + " " + text_secondary).strip()
        
        if all_text:
            details['recognized_text'] = all_text
            logger.warning(f"⚠️ Не удалось выделить численное значение веса из текста: {all_text}")
            details['error'] = "Не удалось определить вес из распознанного текста"
            return None, f"⚠️ В изображении найдены числа, но не ясно какое из них вес:\n\n_{all_text}_\n\n📷 Пожалуйста, пришлите новое фото чище и под правильным углом", details
        else:
            logger.warning(f"⚠️ Текст не распознан на изображении")
            details['error'] = "Не распознан текст на изображении"
            return None, "🤔 На фотографии не видно четкого текста с весом. Попробуйте:\n- Фотографировать прямо табло весов\n- Убедиться в хорошем освещении\n- Убрать блики и отражения", details
    
    except Exception as e:
        logger.error(f"❌ Ошибка обработки изображения: {e}")
        details['error'] = str(e)
        return None, f"❌ Ошибка обработки изображения: {str(e)}", details


def extract_weight_value_advanced(text: str) -> Tuple[Optional[float], str, List[float]]:
    """
    Простая и надежная логика извлечения веса
    - Ищет числовые последовательности (игнорируя точки/запятые)
    - Пропускает те, что начинаются с 0
    - Исключает строки только с нулями
    
    Args:
        text: Текст, полученный от OCR
        
    Returns:
        Кортеж (вес_в_кг, метод_распознавания, список_кандидатов)
    """
    try:
        if not text or not isinstance(text, str) or not text.strip():
            return None, 'empty', []
        
        logger.info(f"   📝 Анализируем текст: {repr(text[:200])}")
        
        # Разбиваем текст на строки
        lines = text.split('\n')
        candidates = []
        
        for line_idx, line in enumerate(lines):
            try:
                line = str(line).strip() if line else ""
                if not line:
                    continue
                
                logger.info(f"   Строка {line_idx}: '{line}'")
                
                # Убираем пробелы внутри чисел
                line_cleaned = re.sub(r'\s+([0-9])', r'\1', line)
                line_cleaned = re.sub(r'([0-9])\s+', r'\1', line_cleaned)
                
                # Ищем все последовательности цифр и точек/запятых
                number_matches = re.findall(r'([0-9][0-9.,]*[0-9]|[0-9]+)', line_cleaned)
                
                for match in number_matches:
                    try:
                        # Убираем точки и запятые из числа
                        clean_num = str(match).replace('.', '').replace(',', '')
                        
                        if not clean_num or not clean_num[0].isdigit():
                            continue
                        
                        # Пропускаем если начинается с 0
                        if clean_num[0] == '0':
                            logger.info(f"      ⏭️ Пропускаем (начинается с 0): {match}")
                            continue
                        
                        # Пропускаем если только нули
                        if all(c == '0' for c in clean_num):
                            logger.info(f"      ⏭️ Пропускаем (только нули): {match}")
                            continue
                        
                        # Конвертируем в число
                        value = float(clean_num)
                        logger.info(f"      ✓ Найдено число: {match} → {value}")
                        candidates.append(value)
                    except (ValueError, TypeError, AttributeError) as e:
                        logger.debug(f"      Ошибка обработки {match}: {e}")
                        continue
            except Exception as e:
                logger.warning(f"   Ошибка обработки строки {line_idx}: {e}")
                continue
        
        # Фильтруем кандидатов
        valid_candidates = [c for c in candidates if isinstance(c, (int, float)) and 100 <= c <= 100000]
        
        if valid_candidates:
            logger.info(f"   ✅ Валидные кандидаты: {valid_candidates}")
            final_weight = valid_candidates[0]
            logger.info(f"   ✅ Выбран: {final_weight}")
            return final_weight, 'direct_match', valid_candidates
        
        logger.warning(f"❌ Вес не найден в тексте")
        return None, 'not_found', candidates
    
    except Exception as e:
        logger.error(f"❌ Ошибка в extract_weight_value_advanced: {e}")
        return None, 'error', []


def extract_weight_value(text: str) -> Optional[float]:
    """
    Извлечь значение веса из текста (обратная совместимость)
    
    Args:
        text: Текст, полученный от OCR
        
    Returns:
        Вес в кг или None
    """
    weight, _, _ = extract_weight_value_advanced(text)
    return weight


def validate_weight(weight: float) -> bool:
    """
    Проверить, является ли значение разумным весом для грузовика
    
    Args:
        weight: Вес в кг
        
    Returns:
        True если вес в допустимом диапазоне
    """
    return 5000 <= weight <= 60000

