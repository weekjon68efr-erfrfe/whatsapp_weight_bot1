"""
Модуль для распознавания веса с фотографий весов
Использует PaddleOCR для распознавания цифр на LED табло
"""
import cv2
import numpy as np
import re
import os
from typing import Tuple, Optional, List, Dict
import logging

logger = logging.getLogger(__name__)

# Допустимый диапазон веса — можно переопределить через окружение
try:
    MIN_WEIGHT = int(os.getenv('MIN_WEIGHT', '1'))
except Exception:
    MIN_WEIGHT = 1
try:
    MAX_WEIGHT = int(os.getenv('MAX_WEIGHT', '150000'))
except Exception:
    MAX_WEIGHT = 150000

# Инициализируем PaddleOCR
try:
    from paddleocr import PaddleOCR
    PADDLE_AVAILABLE = True
    ocr = PaddleOCR(use_angle_cls=True, lang='en')
    logger.info("✅ PaddleOCR инициализирована")
except ImportError:
    PADDLE_AVAILABLE = False
    logger.warning("⚠️ PaddleOCR не установлена")

# Попытка инициализировать OpenAI (опционально)
try:
    import openai
    OPENAI_AVAILABLE = bool(os.getenv('OPENAI_API_KEY'))
    if OPENAI_AVAILABLE:
        openai.api_key = os.getenv('OPENAI_API_KEY')
        logger.info("✅ OpenAI client initialized (OPENAI_API_KEY detected)")
    else:
        logger.info("🔎 OpenAI API key not set; GPT assist disabled")
except Exception:
    OPENAI_AVAILABLE = False
    logger.info("🔎 OpenAI package not installed; GPT assist disabled")

# Попытка инициализировать pytesseract (опционально)
try:
    import pytesseract
    from PIL import Image
    TESSERACT_AVAILABLE = True
    logger.info("🔎 pytesseract available")
except Exception:
    TESSERACT_AVAILABLE = False
    logger.info("🔎 pytesseract not available")


def extract_weight_from_image(image_path: str) -> Tuple[Optional[float], str, Dict]:
    """
    Распознать вес с фотографии весов используя PaddleOCR
    
    Args:
        image_path: путь к файлу с изображением
        
    Returns:
        Кортеж (вес_в_кг, сообщение, детали)
    """
    details = {
        'method': 'none',
        'error': None,
        'text': '',
        'candidates': []
    }
    
    try:
        if not os.path.exists(image_path):
            return None, "❌ Файл фото не найден", details
        
        image = cv2.imread(image_path)
        if image is None:
            return None, "❌ Не удалось открыть фото", details
        
        logger.info(f"🔍 Распознавание из {image_path}")
        
        # Если PaddleOCR доступна
        if PADDLE_AVAILABLE:
            weight, candidates, text = _extract_with_paddle(image)
            details['text'] = text
            details['candidates'] = candidates
            
            if weight is not None:
                details['method'] = 'paddle'
                logger.info(f"✅ Вес распознан: {weight} кг")
                return weight, "", details
            
            logger.debug(f"PaddleOCR: вес не найден в тексте: {text}")
        
        # Fallback: попытка распознать с CV2 + простой парсинг
        weight, candidates = _extract_with_cv2(image)
        if weight is not None:
            details['method'] = 'cv2'
            details['candidates'] = candidates
            logger.info(f"✅ Вес распознан (CV2): {weight} кг")
            return weight, "", details

        # Tesseract fallback (опционально)
        if TESSERACT_AVAILABLE:
            try:
                t_weight, t_candidates, t_text = _extract_with_tesseract(image)
                # Добавим текст tesseract в детали для диагностики
                details['text'] = (details.get('text', '') + ' ' + (t_text or '')).strip()
                if t_weight is not None:
                    details['method'] = 'tesseract'
                    details['candidates'] = t_candidates
                    logger.info(f"✅ Вес распознан (Tesseract): {t_weight} кг")
                    return t_weight, "", details
            except Exception as e:
                logger.debug(f"Tesseract fallback failed: {e}")

        # Попробуем GPT-помощника по распознанному тексту (опционально)
        if OPENAI_AVAILABLE:
            try:
                gpt_weight, gpt_candidates = _gpt_assist_from_text(details.get('text', ''))
                if gpt_weight is not None:
                    details['method'] = 'gpt'
                    details['candidates'] = gpt_candidates
                    logger.info(f"✅ Вес распознан (GPT): {gpt_weight} кг")
                    return gpt_weight, "", details
            except Exception as e:
                logger.debug(f"GPT assist failed: {e}")

        # Ничего не сработало
        return None, """❌ Не удалось автоматически определить вес

💡 Пожалуйста:
1. Отправьте *новое фото* - более четкое табло весов
2. ИЛИ введите вес *вручную* (например: 22380)

⚠️ Совет: фото должно быть четким и ярким, табло видно полностью""", details
    
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()
        details['error'] = str(e)
        return None, f"❌ Ошибка обработки фото: {str(e)}", details


def _extract_with_paddle(image: np.ndarray) -> Tuple[Optional[float], List, str]:
    """Распознавание с помощью PaddleOCR"""
    try:
        # Улучшаем контраст для лучшего распознавания
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        
        # CLAHE для улучшения контраста
        clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
        enhanced = clahe.apply(gray)
        
        # Конвертируем обратно в BGR для PaddleOCR
        enhanced_bgr = cv2.cvtColor(enhanced, cv2.COLOR_GRAY2BGR)
        
        # Запускаем OCR
        logger.info("   Запуск PaddleOCR...")
        results = ocr.ocr(enhanced_bgr, cls=True)

        if not results or not results[0]:
            logger.debug("   PaddleOCR вернула пусто")
            return None, [], ""

        # Собираем распознанные сегменты с confidence
        all_text = ""
        detected_segments: List[Tuple[str, float]] = []
        for item in results[0]:
            # Попытка получить текст и confidence в различных возможных форматах
            text = None
            conf = None
            try:
                # Формат: [box, (text, confidence)]
                if isinstance(item, (list, tuple)) and len(item) >= 2 and isinstance(item[1], (list, tuple)):
                    candidate = item[1]
                    if isinstance(candidate, (list, tuple)) and len(candidate) >= 2:
                        text = candidate[0]
                        conf = float(candidate[1])
                # Ранее код использовал item[0] как текст — на случай старых версий
                if text is None:
                    if isinstance(item, (list, tuple)) and len(item) > 0:
                        maybe = item[0]
                        if isinstance(maybe, str):
                            text = maybe
            except Exception:
                pass

            if text:
                text = str(text).strip()
                if conf is None:
                    # Если confidence не извлечён — назначаем низкое по умолчанию
                    conf = 0.0
                detected_segments.append((text, conf))
                all_text += text + " "
                logger.debug(f"   Распознано: {text} (conf={conf})")

        logger.info(f"   Полный текст: {all_text}")

        # Попробуем сначала собрать все числовые сегменты с приемлемым confidence
        numeric_concat = ""
        for seg, conf in detected_segments:
            if re.search(r"\d", seg) and conf >= 0.35:
                numeric_concat += seg + " "

        # Если собрали числовые сегменты — парсим их в приоритетном порядке
        if numeric_concat:
            weight, candidates = _parse_weight(numeric_concat)
            if weight is not None:
                return weight, candidates, all_text

        # Иначе парсим весь распознанный текст
        weight, candidates = _parse_weight(all_text)

        return weight, candidates, all_text
    
    except Exception as e:
        logger.debug(f"PaddleOCR ошибка: {e}")
        return None, [], ""


def _extract_led_by_color(image: np.ndarray) -> Optional[np.ndarray]:
    """
    Попытаться выделить область семисегментного табло по цвету (красный/оранжевый)
    Возвращает ROI (BGR) или None
    """
    try:
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
        blur = cv2.GaussianBlur(hsv, (5, 5), 0)

        # Диапазоны для красного (две области в HSV) и оранжевого/жёлтого
        lower_red1 = np.array([0, 80, 50])
        upper_red1 = np.array([10, 255, 255])
        lower_red2 = np.array([170, 80, 50])
        upper_red2 = np.array([180, 255, 255])
        lower_orange = np.array([8, 70, 40])
        upper_orange = np.array([25, 255, 255])

        mask1 = cv2.inRange(blur, lower_red1, upper_red1)
        mask2 = cv2.inRange(blur, lower_red2, upper_red2)
        mask3 = cv2.inRange(blur, lower_orange, upper_orange)
        mask = cv2.bitwise_or(mask1, mask2)
        mask = cv2.bitwise_or(mask, mask3)

        # Очистка шума
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return None

        # Ищем самый крупный контур — предполагаем табло
        contours = sorted(contours, key=cv2.contourArea, reverse=True)
        h_img, w_img = image.shape[:2]
        for cnt in contours[:5]:
            area = cv2.contourArea(cnt)
            if area < 200:
                continue
            x, y, w, h = cv2.boundingRect(cnt)
            # пропускаем очень узкие/высокие регионы
            if w < 30 or h < 10:
                continue
            # расширим bbox немного
            pad_x = int(w * 0.08) + 2
            pad_y = int(h * 0.12) + 2
            x0 = max(0, x - pad_x)
            y0 = max(0, y - pad_y)
            x1 = min(w_img, x + w + pad_x)
            y1 = min(h_img, y + h + pad_y)
            roi = image[y0:y1, x0:x1]
            if roi.size == 0:
                continue
            return roi

        return None
    except Exception as e:
        logger.debug(f"LED color extract error: {e}")
        return None


def _extract_with_cv2(image: np.ndarray) -> Tuple[Optional[float], List]:
    """Fallback метод с CV2"""
    try:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        
        # Контраст
        clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
        contrast = clahe.apply(gray)

        # Попробуем сначала выделить табло по цвету (красные/оранжевые светодиоды)
        led_roi = _extract_led_by_color(image)
        if led_roi is not None:
            try:
                # Подготовим ROI для OCR: увеличение и контраст
                roi_gray = cv2.cvtColor(led_roi, cv2.COLOR_BGR2GRAY)
                try:
                    roi_gray = cv2.resize(roi_gray, (roi_gray.shape[1]*2, roi_gray.shape[0]*2), interpolation=cv2.INTER_LINEAR)
                except Exception:
                    pass
                clahe_r = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
                roi_proc = clahe_r.apply(roi_gray)

                # Сначала попробуем Paddle на ROI
                if PADDLE_AVAILABLE:
                    try:
                        roi_bgr = cv2.cvtColor(roi_proc, cv2.COLOR_GRAY2BGR)
                        res = ocr.ocr(roi_bgr, cls=False)
                        collected = ""
                        if res and res[0]:
                            for det in res[0]:
                                try:
                                    if isinstance(det, (list, tuple)) and len(det) >= 2 and isinstance(det[1], (list, tuple)):
                                        collected += str(det[1][0]) + " "
                                    elif isinstance(det[0], str):
                                        collected += str(det[0]) + " "
                                except Exception:
                                    continue
                        if collected:
                            weight, candidates = _parse_weight(collected)
                            if weight is not None:
                                return weight, candidates
                    except Exception:
                        pass

                # Потом Tesseract
                if TESSERACT_AVAILABLE:
                    try:
                        from PIL import Image
                        pil = Image.fromarray(roi_proc)
                        cfg = '--psm 7 -c tessedit_char_whitelist=0123456789'
                        txt = pytesseract.image_to_string(pil, config=cfg)
                        if txt:
                            weight, candidates = _parse_weight(txt)
                            if weight is not None:
                                return weight, candidates
                    except Exception:
                        pass
            except Exception:
                pass
        
        # Условная бинаризация и адаптивная обработка для извлечения цифр
        # Попробуем adaptiveThreshold для неравномерного освещения
        try:
            adaptive = cv2.adaptiveThreshold(contrast, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                             cv2.THRESH_BINARY_INV, 31, 9)
        except Exception:
            _, adaptive = cv2.threshold(contrast, 150, 255, cv2.THRESH_BINARY_INV)

        # Морфология для слияния компонент
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
        adaptive = cv2.morphologyEx(adaptive, cv2.MORPH_CLOSE, kernel, iterations=2)
        adaptive = cv2.morphologyEx(adaptive, cv2.MORPH_OPEN, kernel, iterations=1)

        contours, _ = cv2.findContours(adaptive, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        all_numbers = ""
        for cnt in contours:
            area = cv2.contourArea(cnt)
            if 50 < area < 20000:
                x, y, w, h = cv2.boundingRect(cnt)
                if 6 < w < 400 and 8 < h < 200:
                    roi = contrast[y:y+h, x:x+w]

                    # Увеличим ROI для улучшения OCR
                    scale = 2
                    try:
                        roi = cv2.resize(roi, (w*scale, h*scale), interpolation=cv2.INTER_LINEAR)
                    except Exception:
                        pass

                    # Порог и очистка шума внутри ROI
                    try:
                        roi = cv2.adaptiveThreshold(roi, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                                     cv2.THRESH_BINARY, 15, 6)
                    except Exception:
                        _, roi = cv2.threshold(roi, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

                    if PADDLE_AVAILABLE:
                        try:
                            roi_bgr = cv2.cvtColor(roi, cv2.COLOR_GRAY2BGR)
                            results = ocr.ocr(roi_bgr, cls=False)
                            if results and results[0]:
                                for det in results[0]:
                                    # попытаемся получить текст/конф
                                    txt = None
                                    try:
                                        if isinstance(det, (list, tuple)) and len(det) >= 2 and isinstance(det[1], (list, tuple)):
                                            txt = det[1][0]
                                        elif isinstance(det[0], str):
                                            txt = det[0]
                                    except Exception:
                                        txt = None
                                    if txt:
                                        all_numbers += str(txt) + " "
                        except Exception:
                            pass

        if all_numbers:
            weight, candidates = _parse_weight(all_numbers)
            return weight, candidates

        return None, []
    
    except Exception as e:
        logger.debug(f"CV2 ошибка: {e}")
        return None, []


def _extract_with_tesseract(image: np.ndarray) -> Tuple[Optional[float], List, str]:
    """Попытка распознать цифры с помощью pytesseract. Возвращает (weight, candidates, raw_text)."""
    try:
        attempts_text = ""
        # Предобработка общего изображения
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
        proc = clahe.apply(gray)

        # Попробуем несколько конфигураций: full image и ROI по контурам
        pil = None
        try:
            pil = Image.fromarray(proc)
        except Exception:
            pil = None

        # Попытка 1: вся картинка, PSM 7 (single text line), цифры только
        try:
            if pil is not None:
                cfg = '--psm 7 -c tessedit_char_whitelist=0123456789'
                txt = pytesseract.image_to_string(pil, config=cfg)
                if txt:
                    attempts_text += txt + ' '
        except Exception:
            pass

        # Попытка 2: найти яркие/тёмные контуры и распознать каждый ROI
        try:
            _, thr = cv2.threshold(proc, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            thr = cv2.bitwise_not(thr)
            kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
            thr = cv2.morphologyEx(thr, cv2.MORPH_CLOSE, kernel, iterations=2)
            contours, _ = cv2.findContours(thr, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            for cnt in contours:
                area = cv2.contourArea(cnt)
                if area < 30 or area > 20000:
                    continue
                x, y, w, h = cv2.boundingRect(cnt)
                if w < 6 or h < 6:
                    continue
                roi = proc[y:y+h, x:x+w]
                try:
                    roi = cv2.resize(roi, (max(32, w*3), max(32, h*3)), interpolation=cv2.INTER_LINEAR)
                except Exception:
                    pass
                try:
                    pil_roi = Image.fromarray(roi)
                    cfg = '--psm 7 -c tessedit_char_whitelist=0123456789'
                    txt = pytesseract.image_to_string(pil_roi, config=cfg)
                    if txt:
                        attempts_text += txt + ' '
                except Exception:
                    continue
        except Exception:
            pass

        # Финальный парсинг собранного текста
        weight, candidates = _parse_weight(attempts_text)
        return weight, candidates, attempts_text

    except Exception as e:
        logger.debug(f"Tesseract error: {e}")
        return None, [], ""


def _parse_weight(text: str) -> Tuple[Optional[float], List]:
    """
    Парсим вес из распознанного текста
    Ищет любое число в диапазоне MIN_WEIGHT-MAX_WEIGHT
    """
    try:
        if not text or not isinstance(text, str):
            return None, []
        
        logger.debug(f"   Парсим текст: {text}")
        
        # На входе: текст с потенциальными цифрами, возможно разделёнными пробелами/запятыми/точками
        # Ищем все фрагменты, содержащие цифры и знаки разделителей
        raw_numbers = re.findall(r'[\d\.,\s]+', text)
        candidates: List[float] = []

        def _clean_number_string(s: str) -> Optional[float]:
            s = s.strip()
            if not s or not re.search(r'\d', s):
                return None
            # Убираем точки и запятые — десятичных дробей нет, считаем только целые цифры
            s = s.replace('.', '')
            s = s.replace(',', '')
            # Удаляем все не-цифры (включая пробелы)
            s = re.sub(r'[^0-9]', '', s)
            if not s:
                return None
            try:
                return float(s)
            except Exception:
                return None

        for raw in raw_numbers:
            val = _clean_number_string(raw)
            if val is None:
                continue
            if MIN_WEIGHT <= val <= MAX_WEIGHT:
                candidates.append(val)
                logger.debug(f"      ✓ Добавлен кандидат: {val}")
            else:
                logger.debug(f"      ✗ Число {val} вне диапазона {MIN_WEIGHT}-{MAX_WEIGHT}")

        if candidates:
            # Возвращаем наиболее правдоподобный кандидат — максимально крупный (табло обычно показывает полный вес)
            best = max(candidates)
            return best, candidates

        logger.debug(f"   ❌ Никаких валидных чисел не найдено")
        return None, candidates
    
    except Exception as e:
        logger.error(f"Ошибка парсинга: {e}")
        return None, []


def _gpt_assist_from_text(text: str) -> Tuple[Optional[float], List]:
    """Использовать GPT (через OpenAI) для выбора наиболее вероятного веса из предоставленного текста.

    Возвращает (weight, candidates)
    """
    try:
        if not OPENAI_AVAILABLE:
            return None, []

        # Формируем подсказку для GPT из текста OCR
        prompt = (
            "Вам дан неструктурированный текст, полученный из OCR с табло весов. "
            "Найдите одно целое число (в килограммах) в диапазоне 100-150000, которое наиболее вероятно соответствует весу на табло. "
            "Если такого числа нет, ответьте SINGLE WORD: NONE. "
            "Вход (OCR):\n```"
        ) + text + "\n```"

        try:
            resp = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "You extract a single integer weight in kg from noisy OCR text. Reply with the integer only or NONE."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=30,
                temperature=0.0,
            )
            gpt_text = resp['choices'][0]['message']['content'].strip()
        except Exception as e:
            logger.debug(f"OpenAI request failed: {e}")
            return None, []

        # Парсим ответ GPT на предмет числа
        if not gpt_text or gpt_text.upper().strip() == 'NONE':
            return None, []

        # Ищем числа в ответе
        nums = re.findall(r"\d+", gpt_text)
        candidates = []
        for n in nums:
            try:
                v = float(n)
                if 100 <= v <= 150000:
                    candidates.append(v)
            except Exception:
                continue

        if candidates:
            return max(candidates), candidates

        return None, []
    except Exception as e:
        logger.debug(f"GPT assist internal error: {e}")
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
        return MIN_WEIGHT <= weight <= MAX_WEIGHT
    except:
        return False
