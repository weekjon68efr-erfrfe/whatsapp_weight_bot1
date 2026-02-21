"""
Модуль для распознавания веса с фотографий весов
Использует Tesseract OCR с fallback на ручной ввод
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
    
    Args:
        image_path: путь к файлу с изображением
        
    Returns:
        Кортеж (вес_в_кг, сообщение, детали)
    """
    details = {
        'method': 'none',
        'error': None,
        'candidates': []
    }
    
    try:
        if not os.path.exists(image_path):
            return None, "❌ Файл фото не найден", details
        
        image = cv2.imread(image_path)
        if image is None:
            return None, "❌ Не удалось открыть фото", details
        
        logger.info(f"🔍 Распознавание из {image_path}")
        
        # Попытка 1: Tesseract
        if TESSERACT_AVAILABLE:
            weight, candidates = _extract_with_tesseract(image)
            if weight is not None:
                details['method'] = 'tesseract'
                details['candidates'] = candidates
                return weight, "", details
        
        # Попытка 2: Простой CV2 метод
        weight, candidates = _extract_with_cv2(image)
        if weight is not None:
            details['method'] = 'cv2'
            details['candidates'] = candidates
            return weight, "", details
        
        # Ничего не сработало
        return None, """❌ Не удалось автоматически определить вес

💡 Пожалуйста:
1. Отправьте *новое фото* (более четкое табло)
2. ИЛИ введите вес *вручную* (например: 15000)""", details
    
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        details['error'] = str(e)
        return None, f"❌ Ошибка обработки: {str(e)}", details


def _extract_with_tesseract(image: np.ndarray) -> Tuple[Optional[float], List]:
    """Распознавание с помощью Tesseract"""
    try:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        
        # Улучшение контраста
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        enhanced = clahe.apply(gray)
        
        # Бинаризация
        _, binary = cv2.threshold(enhanced, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        
        # OCR
        text = pytesseract.image_to_string(binary, lang='rus+eng')
        if not text or not isinstance(text, str):
            return None, []
        
        weight, candidates = _parse_weight(text)
        return weight, candidates
    except Exception as e:
        logger.debug(f"Tesseract ошибка: {e}")
        return None, []


def _extract_with_cv2(image: np.ndarray) -> Tuple[Optional[float], List]:
    """Попытка распознать вес с помощью CV2"""
    try:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        
        # Контраст
        clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
        contrast = clahe.apply(gray)
        
        # Ищем светлые области (цифры)
        _, white_mask = cv2.threshold(contrast, 150, 255, cv2.THRESH_BINARY)
        
        # Морфология
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
        white_mask = cv2.morphologyEx(white_mask, cv2.MORPH_CLOSE, kernel, iterations=2)
        white_mask = cv2.morphologyEx(white_mask, cv2.MORPH_OPEN, kernel, iterations=1)
        
        # Находим контуры
        contours, _ = cv2.findContours(white_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        # Ищем цифры
        all_text = ""
        for cnt in contours:
            area = cv2.contourArea(cnt)
            if 50 < area < 10000:
                x, y, w, h = cv2.boundingRect(cnt)
                if 8 < w < 100 and 10 < h < 100:
                    roi = contrast[y:y+h, x:x+w]
                    if TESSERACT_AVAILABLE:
                        try:
                            text = pytesseract.image_to_string(roi, lang='rus+eng', config='--psm 6')
                            if text:
                                all_text += text
                        except:
                            pass
        
        if all_text:
            weight, candidates = _parse_weight(all_text)
            return weight, candidates
        
        return None, []
    except Exception as e:
        logger.debug(f"CV2 ошибка: {e}")
        return None, []


def _parse_weight(text: str) -> Tuple[Optional[float], List]:
    """Парсим вес из текста"""
    try:
        if not text or not isinstance(text, str):
            return None, []
        
        # Ищем все числа
        numbers = re.findall(r'\d+', text)
        candidates = []
        
        for num_str in numbers:
            try:
                num = float(num_str)
                if 100 <= num <= 100000:
                    candidates.append(num)
            except:
                pass
        
        if candidates:
            return candidates[0], candidates
        
        return None, candidates
    except Exception as e:
        logger.error(f"Ошибка парсинга: {e}")
        return None, []


def validate_weight(weight: float) -> bool:
    """Проверить вес"""
    try:
        return 100 <= weight <= 100000
    except:
        return False
