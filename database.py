import sqlite3
import os
import json
from datetime import datetime
from typing import Optional, Dict, List, Any


class Database:
    """Класс для работы с SQLite базой данных"""
    
    def __init__(self, db_path: str = 'data/database.db'):
        self.db_path = db_path
        self.init_db()
    
    def init_db(self):
        """Инициализация базы данных с таблицами"""
        os.makedirs('data', exist_ok=True)
        
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row  # Для удобства получения данных как словарей
        cursor = conn.cursor()
        
        # Таблица водителей
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS drivers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phone TEXT UNIQUE NOT NULL,
                full_name TEXT,
                personal_phone TEXT,
                truck_number TEXT,
                is_registered BOOLEAN DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Добавить колонку truck_number если её еще нет
        try:
            cursor.execute("ALTER TABLE drivers ADD COLUMN truck_number TEXT")
        except:
            pass  # Колонка уже существует
        
        # Таблица машин и их весов
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS vehicles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                truck_number TEXT UNIQUE NOT NULL,
                last_weight REAL DEFAULT 0,
                last_station TEXT,
                last_weighing_date TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Таблица взвешиваний (отчеты)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS weighings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                driver_phone TEXT NOT NULL,
                truck_number TEXT NOT NULL,
                driver_name TEXT,
                client_name TEXT,
                previous_weight REAL,
                current_weight REAL NOT NULL,
                weight_difference REAL,
                station_name TEXT,
                photo_path TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (driver_phone) REFERENCES drivers (phone),
                FOREIGN KEY (truck_number) REFERENCES vehicles (truck_number)
            )
        ''')
        
        # Таблица состояний пользователей для диалога
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_states (
                phone TEXT PRIMARY KEY,
                state TEXT,
                step TEXT,
                temp_data TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        conn.commit()
        conn.close()
        print("✅ База данных инициализирована")
    
    def get_connection(self) -> sqlite3.Connection:
        """Получить соединение с базой данных"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn
    
    # ==================== ВОДИТЕЛИ ====================
    
    def get_or_create_driver(self, phone: str, full_name: str = None, personal_phone: str = None) -> Dict:
        """Получить или создать водителя"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM drivers WHERE phone = ?", (phone,))
        result = cursor.fetchone()
        
        if result:
            conn.close()
            return dict(result)
        
        # Создаем нового водителя (не зарегистрированного)
        cursor.execute(
            "INSERT INTO drivers (phone, full_name, personal_phone) VALUES (?, ?, ?)",
            (phone, full_name, personal_phone)
        )
        conn.commit()
        cursor.execute("SELECT * FROM drivers WHERE phone = ?", (phone,))
        result = cursor.fetchone()
        conn.close()
        return dict(result)
    
    def register_driver(self, phone: str, full_name: str, personal_phone: str, truck_number: str = None) -> bool:
        """Зарегистрировать водителя"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            # Сначала проверяем, есть ли водитель
            cursor.execute("SELECT * FROM drivers WHERE phone = ?", (phone,))
            result = cursor.fetchone()
            
            if result:
                # Обновляем существующего водителя
                cursor.execute(
                    "UPDATE drivers SET full_name = ?, personal_phone = ?, truck_number = ?, is_registered = 1, updated_at = CURRENT_TIMESTAMP WHERE phone = ?",
                    (full_name, personal_phone, truck_number, phone)
                )
            else:
                # Создаем нового зарегистрированного водителя
                cursor.execute(
                    "INSERT INTO drivers (phone, full_name, personal_phone, truck_number, is_registered) VALUES (?, ?, ?, ?, 1)",
                    (phone, full_name, personal_phone, truck_number)
                )
            
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"Ошибка регистрации: {e}")
            conn.close()
            return False
    
    def is_driver_registered(self, phone: str) -> bool:
        """Проверить, зарегистрирован ли водитель"""
        driver = self.get_driver(phone)
        return driver and driver.get('is_registered', 0) == 1
    
    def update_driver(self, phone: str, full_name: str = None, personal_phone: str = None, truck_number: str = None) -> bool:
        """Обновить информацию о водителе"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            updates = []
            params = []
            
            if full_name:
                updates.append("full_name = ?")
                params.append(full_name)
            if personal_phone:
                updates.append("personal_phone = ?")
                params.append(personal_phone)
            if truck_number is not None:
                updates.append("truck_number = ?")
                params.append(truck_number)
            
            if updates:
                updates.append("updated_at = CURRENT_TIMESTAMP")
                params.append(phone)
                query = f"UPDATE drivers SET {', '.join(updates)} WHERE phone = ?"
                cursor.execute(query, params)
                conn.commit()
            
            conn.close()
            return True
        except Exception as e:
            print(f"Ошибка обновления водителя: {e}")
            conn.close()
            return False
    
    def get_driver(self, phone: str) -> Optional[Dict]:
        """Получить водителя по номеру телефона"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM drivers WHERE phone = ?", (phone,))
        result = cursor.fetchone()
        conn.close()
        return dict(result) if result else None
    
    # ==================== МАШИНЫ ====================
    
    def get_or_create_vehicle(self, truck_number: str) -> Dict:
        """Получить или создать машину"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM vehicles WHERE truck_number = ?", (truck_number,))
        result = cursor.fetchone()
        
        if result:
            conn.close()
            return dict(result)
        
        # Создаем новую машину
        cursor.execute(
            "INSERT INTO vehicles (truck_number) VALUES (?)",
            (truck_number,)
        )
        conn.commit()
        cursor.execute("SELECT * FROM vehicles WHERE truck_number = ?", (truck_number,))
        result = cursor.fetchone()
        conn.close()
        return dict(result)
    
    def get_vehicle(self, truck_number: str) -> Optional[Dict]:
        """Получить машину по номеру"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM vehicles WHERE truck_number = ?", (truck_number,))
        result = cursor.fetchone()
        conn.close()
        return dict(result) if result else None
    
    # ==================== ВЗВЕШИВАНИЯ ====================
    
    def get_last_weight(self, truck_number: str) -> float:
        """Получить последний вес машины из истории взвешиваний"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # Сначала пытаемся получить последний вес из истории взвешиваний
        cursor.execute(
            "SELECT current_weight FROM weighings WHERE truck_number = ? ORDER BY created_at DESC LIMIT 1",
            (truck_number,)
        )
        result = cursor.fetchone()
        conn.close()
        
        # Если есть предыдущие взвешивания - возвращаем последний вес
        if result:
            return result['current_weight']
        
        # Если нет - возвращаем 0
        return 0
    
    def save_weighing(self, data: Dict) -> Optional[Dict]:
        """Сохранить взвешивание (отчет о грузе)"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            # Получаем предыдущий вес
            previous_weight = self.get_last_weight(data['truck_number'])
            
            # Вычисляем разницу
            weight_difference = data['current_weight'] - previous_weight
            
            # Сохраняем взвешивание
            cursor.execute('''
                INSERT INTO weighings 
                (driver_phone, truck_number, driver_name, client_name, previous_weight, current_weight, weight_difference, station_name, photo_path)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                data['driver_phone'],
                data['truck_number'],
                data.get('driver_name', ''),
                data.get('client_name', ''),
                previous_weight,
                data['current_weight'],
                weight_difference,
                data.get('station_name', ''),
                data.get('photo_path', '')
            ))
            
            # Обновляем последний вес в таблице машин
            cursor.execute('''
                UPDATE vehicles 
                SET last_weight = ?, last_station = ?, last_weighing_date = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
                WHERE truck_number = ?
            ''', (data['current_weight'], data.get('station_name', ''), data['truck_number']))
            
            conn.commit()
            
            # Возвращаем сохраненные данные
            cursor.execute("SELECT * FROM weighings WHERE rowid = last_insert_rowid()")
            result = cursor.fetchone()
            conn.close()
            
            return {
                'id': result['id'],
                'weight_difference': weight_difference,
                'previous_weight': previous_weight,
                'current_weight': data['current_weight']
            }
        
        except Exception as e:
            print(f"❌ Ошибка сохранения взвешивания: {e}")
            conn.close()
            return None
    
    def get_driver_history(self, driver_phone: str, limit: int = 10) -> List[Dict]:
        """Получить историю взвешиваний водителя"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute(
            "SELECT * FROM weighings WHERE driver_phone = ? ORDER BY created_at DESC LIMIT ?",
            (driver_phone, limit)
        )
        results = cursor.fetchall()
        conn.close()
        
        return [dict(row) for row in results]
    
    def get_vehicle_history(self, truck_number: str, limit: int = 10) -> List[Dict]:
        """Получить историю взвешиваний машины"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute(
            "SELECT * FROM weighings WHERE truck_number = ? ORDER BY created_at DESC LIMIT ?",
            (truck_number, limit)
        )
        results = cursor.fetchall()
        conn.close()
        
        return [dict(row) for row in results]
    
    def get_last_truck(self, driver_phone: str) -> Optional[str]:
        """Получить последнюю машину водителя"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute(
            "SELECT truck_number FROM weighings WHERE driver_phone = ? ORDER BY created_at DESC LIMIT 1",
            (driver_phone,)
        )
        result = cursor.fetchone()
        conn.close()
        
        return result['truck_number'] if result else None
    
    # ==================== СОСТОЯНИЯ ПОЛЬЗОВАТЕЛЕЙ ====================
    
    def get_user_state(self, phone: str) -> Optional[Dict]:
        """Получить состояние пользователя"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM user_states WHERE phone = ?", (phone,))
        result = cursor.fetchone()
        conn.close()
        
        if result:
            row_dict = dict(result)
            # Парсим JSON если есть
            if row_dict['temp_data']:
                try:
                    row_dict['temp_data'] = json.loads(row_dict['temp_data'])
                except:
                    pass
            return row_dict
        
        return None
    
    def set_user_state(self, phone: str, state: str, step: str = None, temp_data: Any = None) -> bool:
        """Установить состояние пользователя"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            # Преобразуем temp_data в JSON если это словарь или список
            temp_data_str = None
            if temp_data is not None:
                if isinstance(temp_data, (dict, list)):
                    temp_data_str = json.dumps(temp_data, ensure_ascii=False)
                else:
                    temp_data_str = str(temp_data)
            
            cursor.execute('''
                INSERT OR REPLACE INTO user_states 
                (phone, state, step, temp_data, created_at, updated_at)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ''', (phone, state, step, temp_data_str))
            
            conn.commit()
            conn.close()
            return True
        
        except Exception as e:
            print(f"❌ Ошибка установки состояния: {e}")
            conn.close()
            return False
    
    def clear_user_state(self, phone: str) -> bool:
        """Очистить состояние пользователя"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("DELETE FROM user_states WHERE phone = ?", (phone,))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"❌ Ошибка очистки состояния: {e}")
            conn.close()
            return False
