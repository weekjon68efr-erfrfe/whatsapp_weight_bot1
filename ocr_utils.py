"""
Модуль для распознавания веса с фотографий весов используя OCR
Включает автоматическую ориентацию, детектирование цифр и валидацию
"""
import easyocr
import cv2
import numpy as np
import re
import os
from typing import Tuple, Optional, List, Dict
import logging

logger = logging.getLogger(__name__)

# Инициализируем OCR reader один раз (для экономии памяти и скорости)
_reader = None


def get_ocr_reader():
    """Получить или создать OCR reader"""
    global _reader
    if _reader is None:
        logger.info("🔧 Инициализация EasyOCR reader для русского и английского...")
        _reader = easyocr.Reader(['ru', 'en'], gpu=False)
    return _reader


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
    reader = get_ocr_reader()
    
    best_image = image.copy()
    best_count = 0
    best_angle = 0
    
    # Пробуем разные углы поворота
    for angle in [0, 90, 180, 270]:
        rotated = imutils_rotate_bound(image, angle)
        rotated_gray = cv2.cvtColor(rotated, cv2.COLOR_BGR2GRAY)
        
        # Быстрое распознавание для проверки
        try:
            results = reader.readtext(rotated_gray, detail=0)
            # Считаем количество цифр
            digit_count = sum(1 for text in results if any(c.isdigit() for c in text))
            
            if digit_count > best_count:
                best_count = digit_count
                best_image = rotated
                best_angle = angle
        except:
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
    Распознать вес с фотографии весов с детальной информацией о результате
    Использует два варианта предварительной обработки для лучшей надежности
    
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
        'attempts': []  # История попыток разных методов
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
        
        # Предварительная обработка - получаем два варианта
        processed_primary, processed_secondary = preprocess_image(image)
        logger.info(f"   ✓ Изображение обработано (2 варианта)")
        
        reader = get_ocr_reader()
        
        # Пытаемся распознать с первым вариантом обработки
        logger.info(f"   Попытка 1: основной метод обработки")
        results_primary = reader.readtext(processed_primary, detail=1)
        weight, method, candidates = _extract_weight_from_results(results_primary, "primary")
        details['attempts'].append({'method': 'primary', 'weight': weight, 'candidates': candidates})
        
        if weight is not None:
            details['method'] = method
            details['candidates'] = candidates
            details['confidence'] = 0.85
            details['recognized_text'] = ' '.join([text for _, text, _ in results_primary])
            logger.info(f"✅ Вес распознан (попытка 1): {weight} кг")
            return weight, f"✅ Вес распознан: {weight:.0f} кг", details
        
        # Если не совпало - пробуем второй вариант обработки
        logger.info(f"   Попытка 2: альтернативный метод обработки")
        results_secondary = reader.readtext(processed_secondary, detail=1)
        weight, method, candidates = _extract_weight_from_results(results_secondary, "secondary")
        details['attempts'].append({'method': 'secondary', 'weight': weight, 'candidates': candidates})
        
        if weight is not None:
            details['method'] = method
            details['candidates'] = candidates
            details['confidence'] = 0.75  # Слегка ниже, так как это альтернативный метод
            details['recognized_text'] = ' '.join([text for _, text, _ in results_secondary])
            logger.info(f"✅ Вес распознан (попытка 2): {weight} кг")
            return weight, f"✅ Вес распознан: {weight:.0f} кг", details
        
        # Если оба варианта не сработали
        all_text_primary = ' '.join([text for _, text, _ in results_primary]) if results_primary else ""
        all_text_secondary = ' '.join([text for _, text, _ in results_secondary]) if results_secondary else ""
        all_text = (all_text_primary + " " + all_text_secondary).strip()
        
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


def _extract_weight_from_results(results: list, method_name: str) -> Tuple[Optional[float], str, List[float]]:
    """
    Вспомогательная функция для извлечения веса из результатов OCR
    
    Args:
        results: результаты от reader.readtext()
        method_name: название метода обработки (для логирования)
        
    Returns:
        Кортеж (вес, метод_распознавания, кандидаты)
    """
    if not results:
        logger.info(f"   📭 Нет результатов OCR ({method_name})")
        return None, 'empty', []
    
    all_text = " ".join([text for _, text, _ in results])
    logger.info(f"   📝 Распознанный текст ({method_name}): {all_text[:100]}...")
    
    return extract_weight_value_advanced(all_text)


def extract_weight_value_advanced(text: str) -> Tuple[Optional[float], str, List[float]]:
    """
    Извлечь значение веса из текста с информацией о методе
    Ищет числа в диапазоне разумных весов машин (5000-60000 кг)
    Использует продвинутые паттерны распознавания
    
    Args:
        text: Текст, полученный от OCR
        
    Returns:
        Кортеж (вес_в_кг, метод_распознавания, список_кандидатов)
    """
    if not text:
        return None, 'empty', []
    
    # Заменяем запятые на точки и очищаем от артефактов OCR
    text = text.replace(',', '.')
    text = text.replace('O', '0').replace('o', '0')  # Заменяем буквы O на ноль
    text = text.replace('l', '1').replace('I', '1')  # Заменяем L и I на единицу
    text = text.replace('S', '5').replace('s', '5')  # Заменяем S на 5 в числовом контексте
    
    candidates = []
    
    # УРОВЕНЬ 1: Очень специфичные паттерны для весов (максимальный приоритет)
    specific_patterns = [
        # Ищет "TOTAL", "GROSS", "БРУТТО", "GROSS WEIGHT" и т.д. с числом
        (r'(?:total\s+weight|gross\s+weight|t\.weight|g\.weight|брутто|валовой|общий вес)\s*[:\-=]?\s*([0-9]{4,5}(?:[.,][0-9]+)?)', 'gross_weight'),
        (r'(?:net\s+weight|чистый вес|вес груза|n\.weight)\s*[:\-=]?\s*([0-9]{4,5}(?:[.,][0-9]+)?)', 'net_weight'),
        (r'(?:tare|тара|вес машины|тарный вес)\s*[:\-=]?\s*([0-9]{3,5}(?:[.,][0-9]+)?)', 'tare_weight'),
    ]
    
    # УРОВЕНЬ 2: Паттерны с явными числовыми маркерами
    marked_patterns = [
        # Число перед/после явных маркеров килограммов
        (r'([0-9]{4,5}(?:[.,][0-9]+)?)\s*(?:kg|кг|килограмм|kilograms)', 'explicit_kg'),
        (r'(?:wt|вес|weight)\s*[:\-=]?\s*([0-9]{4,5}(?:[.,][0-9]+)?)', 'weight_label'),
        # На цифровых весах часто ряд цифр после точки
        (r'(?:^|\s)([0-9]{4,5})\s*(?:$|\s)', 'isolated_number'),
    ]
    
    # УРОВЕНЬ 3: Общие паттерны с контекстом
    context_patterns = [
        (r'\b([0-9]{5})\b', 'five_digits'),       # 5 цифр - типичная ширина табло
        (r'\b([0-9]{4,5})(?:\s|$)', 'number_end'), # 4-5 цифр в конце слова
    ]
    
    # Применяем все уровни паттернов с приоритизацией
    for patterns, level_name in [
        (specific_patterns, 'SPECIFIC'),
        (marked_patterns, 'MARKED'),
        (context_patterns, 'CONTEXT')
    ]:
        for pattern, pattern_type in patterns:
            matches = re.finditer(pattern, text, re.IGNORECASE | re.MULTILINE)
            for match in matches:
                try:
                    # Нормализуем число (заменяем запятую на точку)
                    value_str = match.group(1).replace(',', '.')
                    value = float(value_str)
                    
                    # Проверяем разумный диапазон для веса грузовика
                    # Расширяем диапазон для большей гибкости
                    if 5000 <= value <= 60000:
                        candidates.append(value)
                        logger.info(f"   [{level_name}] Найден: {value} кг (тип: {pattern_type})")
                        
                        # На уровне SPECIFIC сразу возвращаем (самый надежный)
                        if level_name == 'SPECIFIC':
                            logger.info(f"✅ SPECIFIC совпадение! Возвращаем: {value} кг")
                            return value, pattern_type, [value]
                except (ValueError, AttributeError, IndexError) as e:
                    logger.debug(f"   Ошибка парсинга: {e}")
                    pass
        
        # Если на уровне MARKED нашли - используем
        if level_name == 'MARKED' and candidates:
            final_value = max(candidates)  # Берем максимум (обычно это полный вес)
            logger.info(f"✅ MARKED совпадение! Возвращаем: {final_value} кг")
            return final_value, 'marked', list(set(candidates))
    
    # Если нашли на уровне CONTEXT
    if candidates:
        candidates_unique = list(set(candidates))
        candidates_unique.sort(reverse=True)
        final_value = candidates_unique[0]
        logger.info(f"✅ CONTEXT совпадение! Выбран: {final_value} из {candidates_unique}")
        return final_value, 'context', candidates_unique
    
    # Последняя попытка: просто ищем большие числа в диапазоне
    all_numbers = re.findall(r'\d{4,}(?:\.\d+)?', text)
    if all_numbers:
        try:
            numbers = [float(n) for n in all_numbers]
            # Фильтруем по расширенному диапазону
            filtered = [n for n in numbers if 3000 <= n <= 100000]
            if filtered:
                largest = max(filtered)
                logger.info(f"   [FALLBACK] Найдено крупное число: {largest}")
                return largest, 'fallback_number', sorted(list(set(filtered)), reverse=True)
        except ValueError:
            pass
    
    logger.warning(f"❌ Вес не найден в тексте")
    return None, 'not_found', candidates


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
