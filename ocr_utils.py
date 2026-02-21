"""
Модуль для распознавания веса с фотографий весов
Использует комбинацию OpenCV + Tesseract с надежным fallback
"""
import cv2
import numpy as np
import re
import os
from typing import Tuple, Optional, List, Dict
import logging

logger = logging.getLogger(__name__)

# Пытаемся использовать pytesseract если он доступен
try:
    import pytesseract
    TESSERACT_AVAILABLE = True
    try:
        pytesseract.pytesseract.pytesseract_cmd = '/usr/bin/tesseract'
    except:
        pass
except ImportError:
    TESSERACT_AVAILABLE = False
    logger.warning("pytesseract не установлен, используется fallback режим")


def extract_weight_from_image(image_path: str) -> Tuple[Optional[float], str, Dict]:
    """
    Распознать вес с фотографии весов
    Использует несколько методов для максимальной надежности
    
    Args:
        image_path: путь к файлу с изображением весов
        
    Returns:
        Кортеж (вес_в_кг, сообщение_статуса, детали)
    """
    details = {
        'method': '',
        'error': None,
        'candidates': []
    }
    
    try:
        if not os.path.exists(image_path):
            details['error'] = f"Файл не найден: {image_path}"
            return None, "❌ Файл фото не найден", details
        
        image = cv2.imread(image_path)
        if image is None:
            details['error'] = "Не удалось прочитать изображение"
            return None, "❌ Не удалось открыть фото", details
        
        logger.info(f"🔍 Распознавание из {image_path}")
        
        # Метод 1: Tesseract OCR (если доступен)
        if TESSERACT_AVAILABLE:
            try:
                weight, msg, cands = _extract_with_tesseract(image)
                if weight is not None:
                    details['method'] = 'tesseract'
                    details['candidates'] = cands
                    logger.info(f"✅ Tesseract: {weight} кг")
                    return weight, f"✅ Вес: {weight:.0f} кг", details
                logger.debug("Tesseract вернул None")
            except Exception as e:
                logger.debug(f"Tesseract ошибка: {e}")
        
        # Метод 2: Простой CV2 метод (поиск цифр на контрастных областях)
        try:
            weight, msg, cands = _extract_with_cv2(image)
            if weight is not None:
                details['method'] = 'cv2'
                details['candidates'] = cands
                logger.info(f"✅ CV2: {weight} кг")
                return weight, f"✅ Вес: {weight:.0f} кг", details
            logger.debug("CV2 вернул None")
        except Exception as e:
            logger.debug(f"CV2 ошибка: {e}")
        
        # Если ничего не сработало - предлагаем ручной ввод
        logger.warning("⚠️ Автоматическое распознавание не удалось")
        details['error'] = "Подлинность не установлена"
        
        return None, """❌ Не удалось автоматически определить вес

👉 *Пожалуйста:*
1. Отправьте *новое фото* (более четкое табло)
2. ИЛИ введите вес *вручную* (например: 15000)

💡 Совет: фото должно быть четким с видимыми цифрами на табло""", details
    
    except Exception as e:
        logger.error(f"❌ Фатальная ошибка: {e}")
        details['error'] = str(e)
        return None, f"❌ Ошибка обработки: {str(e)}", details


def _extract_with_tesseract(image: np.ndarray) -> Tuple[Optional[float], str, List]:
    """Распознавание с помощью Tesseract OCR"""
    try:
        # Предварительная обработка
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        
        # CLAHE для улучшения контраста
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        enhanced = clahe.apply(gray)
        
        # Бинаризация
        _, binary = cv2.threshold(enhanced, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        
        # OCR
        text = pytesseract.image_to_string(binary, lang='rus+eng')
        if not text or not isinstance(text, str):
            return None, "", []
        
        # Парсим текст
        weight, candidates = _parse_weight_from_text(text)
        return weight, "", candidates
    except Exception as e:
        logger.debug(f"Tesseract ошибка: {e}")
        return None, "", []


def _extract_with_cv2(image: np.ndarray) -> Tuple[Optional[float], str, List]:
    """
    Попытка распознать вес без OCR
    Ищет области с белыми цифрами на темном фоне
    """
    try:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        
        # Усиливаем контраст
        clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
        contrast = clahe.apply(gray)
        
        # Ищем белые области (обычно цифры светлые)
        _, white_mask = cv2.threshold(contrast, 150, 255, cv2.THRESH_BINARY)
        
        # Морфологические операции
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
        white_mask = cv2.morphologyEx(white_mask, cv2.MORPH_CLOSE, kernel, iterations=2)
        white_mask = cv2.morphologyEx(white_mask, cv2.MORPH_OPEN, kernel, iterations=1)
        
        # Находим контуры
        contours, _ = cv2.findContours(white_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        # Ищем прямоугольники похожие на цифры
        digit_boxes = []
        for cnt in contours:
            area = cv2.contourArea(cnt)
            if 50 < area < 10000:  # Примерный размер цифры
                x, y, w, h = cv2.boundingRect(cnt)
                if 8 < w < 100 and 10 < h < 100:  # Размеры цифры
                    digit_boxes.append((x, y, w, h))
        
        if digit_boxes:
            # Извлекаем текст из всех найденных регионов
            full_text = ""
            for x, y, w, h in sorted(digit_boxes, key=lambda b: b[0]):
                roi = contrast[y:y+h, x:x+w]
                # Пытаемся распознать цифру (простой метод)
                if TESSERACT_AVAILABLE:
                    try:
                        text = pytesseract.image_to_string(roi, lang='rus+eng', config='--psm 6')
                        if text:
                            full_text += text
                    except:
                        pass
            
            if full_text:
                weight, candidates = _parse_weight_from_text(full_text)
                if weight is not None:
                    return weight, "", candidates
        
        return None, "", []
    except Exception as e:
        logger.debug(f"CV2 ошибка: {e}")
        return None, "", []


def _parse_weight_from_text(text: str) -> Tuple[Optional[float], List]:
    """
    Парсим вес из распознанного текста
    Ищет любое число в диапазоне 100-100000
    """
    try:
        if not text or not isinstance(text, str):
            return None, []
        
        # Ищем все числа в тексте
        numbers = re.findall(r'\d+', text)
        candidates = []
        
        for num_str in numbers:
            try:
                num = float(num_str)
                # Фильтруем по разумному диапазону для веса груза
                if 100 <= num <= 100000:
                    candidates.append(num)
            except (ValueError, TypeError):
                pass
        
        if candidates:
            # Возвращаем первый валидный вес
            return candidates[0], candidates
        
        return None, candidates
    except Exception as e:
        logger.error(f"Ошибка парсинга: {e}")
        return None, []


def validate_weight(weight: float) -> bool:
    """
    Проверить разумность значения веса
    
    Args:
        weight: Вес в кг
        
    Returns:
        True если вес в допустимом диапазоне
    """
    try:
        return 100 <= weight <= 100000
    except:
        return False

