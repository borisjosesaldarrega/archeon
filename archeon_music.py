# =========================================================
# ARCHIVO: archeon_music.py (CAMBIO EN TIEMPO REAL - OPTIMIZADO)
# =========================================================
import threading
import queue
import time
import random
import re
import subprocess
import numpy as np
import sounddevice as sd
import yt_dlp
from collections import deque
import os
import sys

# Importar función de ruta (CORREGIDA PARA .EXE)
def get_ffmpeg_path():
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        # En modo EXE, buscar en el paquete temporal primero
        internal_path = os.path.join(sys._MEIPASS, 'ffmpeg.exe')
        if os.path.exists(internal_path):
            return internal_path
        
        # Si no está en _MEIPASS, buscar en el directorio del ejecutable
        exe_dir = os.path.dirname(sys.executable)
        exe_dir_path = os.path.join(exe_dir, 'ffmpeg.exe')
        if os.path.exists(exe_dir_path):
            return exe_dir_path
    
    # En modo desarrollo, asume que está en el PATH
    return 'ffmpeg'

# =========================================================
# CÁPSULA 2: GESTOR DE MÚSICA (OPTIMIZADO)
# =========================================================
class MusicManager:
    def __init__(self, asistente_ref):
        self.asistente = asistente_ref
        self.ydl_opts = {
            'format': 'bestaudio/best', 
            'default_search': 'ytsearch',
            'noplaylist': True, 
            'quiet': True, 
            'no_warnings': True,
            'ignoreerrors': True,
            'source_address': '0.0.0.0',
            'nocheckcertificate': True,
            'extract_flat': False 
        }
        
        # Configuración de audio - SOUNDDEVICE con buffers grandes
        self.stream_out = None
        self.ffmpeg_process = None
        self._reader_thread = None
        self._player_thread = None
        
        # ✅ BUFFER GRANDE para evitar underflow (256 bloques)
        self.audio_data_queue = queue.Queue(maxsize=256)
        
        self._stream_lock = threading.Lock()
        
        # Para detección de dispositivos en tiempo real
        self.current_output_device_id = None
        self.current_output_device_name = None
        self.device_monitor_thread = None
        self.device_check_interval = 0.5  # Balance entre rapidez y CPU
        self.running_device_monitor = True
        
        # Control para cambio de dispositivo MID-SONG
        self._device_change_requested = threading.Event()
        self._new_device_id = None
        self._new_device_name = None
        
        self.track_queue = queue.Queue() 
        self.dj_thread = None
        
        self.current_thumbnail = None
        self.current_title = "Esperando..."
        self.history = [] 
        
        self.is_paused = False
        self.stop_signal = False 
        self.autoplay_enabled = True
        self.internal_volume = 0.5 
        
        # ✅ RUTA FFMPEG CORREGIDA
        self.ffmpeg_path = get_ffmpeg_path()
        print(f">> [MUSIC SYSTEM] Ruta FFmpeg: {self.ffmpeg_path}")
        
        # Iniciar monitor de dispositivos
        self._start_device_monitor()

    def _start_device_monitor(self):
        """Inicia el hilo que monitorea cambios en dispositivos de salida"""
        def monitor_loop():
            print(">> [Audio Monitor] Iniciando monitor de dispositivos de audio...")
            
            # Obtener dispositivo inicial
            default_info = self._get_default_output_device_info()
            self.current_output_device_id = default_info['index']
            self.current_output_device_name = default_info['name']
            last_device_id = self.current_output_device_id
            last_device_name = self.current_output_device_name
            
            print(f">> [Audio Monitor] Dispositivo inicial: {last_device_name} (ID: {last_device_id})")
            
            while self.running_device_monitor:
                try:
                    # Obtener dispositivo predeterminado actual
                    current_info = self._get_default_output_device_info()
                    current_device_id = current_info['index']
                    current_device_name = current_info['name']
                    
                    # Si el dispositivo cambió
                    if current_device_id != last_device_id:
                        print(f">> [Audio Monitor] 🔄 Cambio detectado:")
                        print(f"    Anterior: {last_device_name} (ID: {last_device_id})")
                        print(f"    Nuevo: {current_device_name} (ID: {current_device_id})")
                        
                        last_device_id = current_device_id
                        last_device_name = current_device_name
                        
                        # Guardar nuevo dispositivo y solicitar cambio
                        self._new_device_id = current_device_id
                        self._new_device_name = current_device_name
                        self._device_change_requested.set()  # Señal para cambiar
                    
                    time.sleep(self.device_check_interval)
                except Exception as e:
                    print(f"!! Error en monitor de audio: {e}")
                    time.sleep(1)
        
        self.device_monitor_thread = threading.Thread(target=monitor_loop, daemon=True)
        self.device_monitor_thread.start()

    def _get_default_output_device_info(self):
        """Obtiene el dispositivo de salida predeterminado usando SoundDevice"""
        try:
            # Obtener dispositivo predeterminado de salida
            devices = sd.query_devices()
            default_output_info = sd.query_devices(kind='output')
            
            # Buscar el índice del dispositivo predeterminado
            default_index = None
            for i, device in enumerate(devices):
                if device['name'] == default_output_info['name'] and device['max_output_channels'] > 0:
                    default_index = i
                    break
            
            if default_index is None:
                # Fallback: buscar el primer dispositivo de salida disponible
                for i, device in enumerate(devices):
                    if device['max_output_channels'] > 0:
                        default_index = i
                        break
            
            if default_index is None:
                # Último fallback
                return {'index': 0, 'name': 'Altavoces', 'max_output_channels': 2, 'default_samplerate': 44100}
            
            device_info = devices[default_index]
            return {
                'index': default_index,
                'name': device_info['name'],
                'max_output_channels': device_info['max_output_channels'],
                'default_samplerate': device_info['default_samplerate']
            }
        except Exception as e:
            print(f"!! Error obteniendo dispositivo: {e}")
            return {'index': 0, 'name': 'Altavoces', 'max_output_channels': 2, 'default_samplerate': 44100}

    def _handle_device_change_mid_song(self):
        """Maneja el cambio de dispositivo DURANTE la reproducción"""
        if not self._device_change_requested.is_set():
            return False
        
        try:
            print(f">> [Audio] 🔄 Cambiando dispositivo durante la canción...")
            
            # Guardar estado actual
            was_playing = not self.is_paused
            
            # Pausar brevemente
            self.is_paused = True
            time.sleep(0.02)  # Reducido a 20ms
            
            # Limpiar stream actual
            self._cleanup_stream_only()
            
            # Actualizar dispositivo actual
            self.current_output_device_id = self._new_device_id
            self.current_output_device_name = self._new_device_name
            
            # Crear nuevo stream
            self._create_audio_stream()
            
            # ✅ NO LIMPIAR LA COLA - mantener datos para continuidad
            # Solo limpiar si hay problemas de sincronización
            if self.audio_data_queue.qsize() > 50:  # Si hay mucho buffer acumulado
                with self.audio_data_queue.mutex:
                    # Mantener solo los últimos 20 elementos para continuidad
                    items = list(self.audio_data_queue.queue)
                    self.audio_data_queue.queue.clear()
                    # Añadir los últimos 20 items de vuelta
                    for item in items[-20:]:
                        try:
                            self.audio_data_queue.put_nowait(item)
                        except:
                            pass
            
            # Reanudar si estaba reproduciendo
            if was_playing:
                time.sleep(0.02)  # Reducido a 20ms
                self.is_paused = False
            
            print(f">> [Audio] ✅ Dispositivo cambiado a: {self.current_output_device_name}")
            
            # Limpiar señal
            self._device_change_requested.clear()
            self._new_device_id = None
            self._new_device_name = None
            
            return True
            
        except Exception as e:
            print(f"!! Error cambiando dispositivo mid-song: {e}")
            self._device_change_requested.clear()
            return False

    def _create_audio_stream(self, device_index=None):
        """Crea un nuevo stream de audio con SoundDevice - OPTIMIZADO"""
        try:
            # Usar el dispositivo actual si no se especifica
            if device_index is None:
                device_index = self.current_output_device_id
            
            # Configuración optimizada
            sample_rate = 44100
            channels = 2
            
            # Función de callback para el stream
            def callback(outdata, frames, time, status):
                if status:
                    if status.output_underflow:
                        # Solo imprimir warning la primera vez
                        pass
                
                if self.stop_signal or self.is_paused:
                    outdata.fill(0)
                    return
                
                try:
                    # Intentar obtener datos de la cola
                    data = self.audio_data_queue.get_nowait()
                    
                    # Convertir a numpy array y aplicar volumen
                    audio_array = np.frombuffer(data, dtype=np.int16)
                    
                    # Aplicar volumen
                    if self.internal_volume < 1.0:
                        audio_array = (audio_array * self.internal_volume).astype(np.int16)
                    
                    # Redimensionar según sea necesario
                    samples_needed = frames * channels
                    if len(audio_array) < samples_needed:
                        # Rellenar con ceros si no hay suficientes datos
                        padded = np.zeros(samples_needed, dtype=np.int16)
                        padded[:len(audio_array)] = audio_array
                        audio_array = padded
                    elif len(audio_array) > samples_needed:
                        audio_array = audio_array[:samples_needed]
                    
                    # Reformatear para sounddevice (canales separados)
                    outdata[:] = audio_array.reshape(-1, channels).astype(np.float32) / 32768.0
                    
                except queue.Empty:
                    # No hay datos, llenar con silencio
                    outdata.fill(0)
                except Exception as e:
                    print(f"!! Error en callback: {e}")
                    outdata.fill(0)
            
            # ✅ CREAR STREAM CON BUFFER GRANDE
            self.stream_out = sd.OutputStream(
                samplerate=sample_rate,
                channels=channels,
                dtype='float32',
                device=device_index,
                callback=callback,
                blocksize=2048,  # ✅ Buffer más grande (antes 1024)
                latency='high'   # ✅ Alta latencia para evitar cortes
            )
            
            # Iniciar stream
            self.stream_out.start()
            return True
            
        except Exception as e:
            print(f"!! Error creando stream con SoundDevice: {e}")
            return False

    def _cleanup_stream_only(self):
        """Limpia solo el stream de forma rápida y segura"""
        try:
            with self._stream_lock:
                if self.stream_out:
                    try:
                        self.stream_out.stop()
                    except:
                        pass
                    try:
                        self.stream_out.close()
                    except:
                        pass
                    finally:
                        self.stream_out = None
        except:
            pass

    def set_music_volume(self, level_0_to_100):
        self.internal_volume = max(0.0, min(1.0, float(level_0_to_100) / 100.0))

    def play_audio_threaded(self, query):
        """Inicia reproducción"""
        print(f">> [Music] Solicitando: {query}")
        
        self.stop_audio(reset_data=False, silent=True)
        time.sleep(0.1)
        
        self.stop_signal = False
        self.autoplay_enabled = True
        self.is_paused = False
        
        # Asegurar monitor activo
        if not self.running_device_monitor:
            self.running_device_monitor = True
            self._start_device_monitor()
        
        # Actualizar dispositivo actual
        device_info = self._get_default_output_device_info()
        self.current_output_device_id = device_info['index']
        self.current_output_device_name = device_info['name']
        
        if self.dj_thread is None or not self.dj_thread.is_alive():
            self.dj_thread = threading.Thread(target=self._dj_loop, args=(query,), daemon=True)
            self.dj_thread.start()
        else:
            with self.track_queue.mutex: self.track_queue.queue.clear()
            self._add_first_track(query)

    def _add_first_track(self, query):
        track = self._get_info(query)
        if track: self.track_queue.put(track)

    def _dj_loop(self, initial_query):
        print(">> [DJ SYSTEM] Iniciando sesión...")
        first_track = self._get_info(initial_query)
        if not first_track:
            self.asistente.voz.decir("No encontré la canción.")
            return
        
        self.track_queue.put(first_track)
        
        while not self.stop_signal and self.autoplay_enabled:
            if self.track_queue.qsize() < 2:
                base_title = self.current_title if self.current_title != "Esperando..." else first_track.get('title')
                threading.Thread(target=self._fetch_next_recommendation, args=(base_title,), daemon=True).start()

            try:
                track = self.track_queue.get(timeout=1) 
            except queue.Empty:
                if self.stop_signal: break 
                continue

            if self.stop_signal or not self.autoplay_enabled:
                print(">> [DJ] Parada detectada antes de reproducir.")
                break

            self._play_track(track)
            
            if self.stop_signal:
                print(">> [DJ] Bucle terminado por orden de usuario.")
                break

        self.current_title = "Detenido"
        self.current_thumbnail = None

    def _fetch_next_recommendation(self, current_title):
        if self.stop_signal or not self.autoplay_enabled: return
        try:
            clean = re.sub(r"[\(\[].*?[\)\]]", "", current_title)
            clean = clean.replace("|", "").replace("ft.", "").replace("feat.", "").strip()
            
            search_term = ""
            if "-" in clean:
                parts = clean.split("-")
                artist = parts[0].strip()
                # Mejorar búsqueda para evitar mixes
                search_term = random.choice([f"{artist} official", f"{artist} playlist", f"{artist} full album"])
            else:
                # Evitar "mix" y "radio" que traen contenido no deseado
                search_term = random.choice([f"{clean} official", f"songs like {clean}"])
            
            if self.stop_signal: return

            info = self._get_info(f"radio:{search_term}")
            
            if info and not self.stop_signal:
                # Verificar si ya está en historial reciente
                track_title = info.get('title', '')
                if track_title in self.history[-5:]:  # Últimas 5 canciones
                    print(f">> [DJ] Ignorando duplicado reciente: {track_title}")
                    return
                    
                self.track_queue.put(info)
                print(f">> [DJ] Añadido a cola: {info.get('title')}")
                
        except Exception as e:
            print(f"!! Error DJ Fetch: {e}")

    def _play_track(self, info):
        """Reproduce una canción con capacidad de cambiar dispositivo MID-SONG"""
        if self.stop_signal: return

        stream_url = info.get('url') or next((f['url'] for f in info.get('formats', []) if f.get('acodec') != 'none'), None)
        if not stream_url: return

        self.current_thumbnail = info.get('thumbnail')
        self.current_title = info.get('title')
        
        self.history.append(self.current_title)
        if len(self.history) > 15: self.history.pop(0)
        
        with self.audio_data_queue.mutex: self.audio_data_queue.queue.clear()
        
        print(f">> [Music] Reproduciendo: {self.current_title}")
        print(f">> [Music] Dispositivo inicial: {self.current_output_device_name}")
        
        # ✅ PRE-BUFFERING antes de iniciar reproducción
        print(">> [Music] Cargando buffer inicial...")
        
        # 1. Iniciar reader primero (para llenar buffer)
        self._start_reader(stream_url)
        
        # 2. Esperar a que se llene un poco el buffer
        buffer_start_time = time.time()
        while self.audio_data_queue.qsize() < 20 and (time.time() - buffer_start_time) < 5.0:
            time.sleep(0.1)
            if self.stop_signal: return
        
        print(f">> [Music] Buffer inicial: {self.audio_data_queue.qsize()} chunks")
        
        # 3. Iniciar player
        self._start_player() 

        # Bucle principal de reproducción CON CHEQUEO DE DISPOSITIVO
        device_check_counter = 0
        
        while True:
            if self.stop_signal: break
            
            # Verificar cada 200ms si hay cambio de dispositivo
            device_check_counter += 1
            if device_check_counter >= 2:  # Cada ~200ms
                if self._device_change_requested.is_set():
                    print(">> [Music] Cambio de dispositivo solicitado, procesando...")
                    self._handle_device_change_mid_song()
                device_check_counter = 0
            
            # Verificar si terminó la canción
            if not (self._reader_thread and self._reader_thread.is_alive()) and self.audio_data_queue.empty():
                break
            
            time.sleep(0.1)  # Pausa corta para no sobrecargar CPU
        
        # Limpiar recursos
        self._cleanup_audio_resources()

    def _get_info(self, query):
        try:
            with yt_dlp.YoutubeDL(self.ydl_opts) as ydl:
                if query.startswith("radio:"):
                    real_query = query.replace("radio:", "")
                    info = ydl.extract_info(f"ytsearch5:{real_query}", download=False)
                    if 'entries' in info and len(info['entries']) > 0:
                        entries = info['entries']
                        # Filtrar mejor para evitar contenido no deseado
                        filtered_entries = []
                        for entry in entries:
                            if not entry:
                                continue
                            title = entry.get('title', '').lower()
                            # Excluir mixes, remixes, covers
                            exclude_keywords = ['mix', 'mashup', 'remix', 'cover', 'live at', 'concert', 'karaoke']
                            if not any(keyword in title for keyword in exclude_keywords):
                                filtered_entries.append(entry)
                        
                        if not filtered_entries:
                            filtered_entries = entries
                        
                        candidates = [e for e in filtered_entries if not any(h.lower() in e.get('title','').lower() for h in self.history)]
                        if not candidates: candidates = filtered_entries
                        return random.choice(candidates)
                    elif 'entries' in info: return info['entries'][0]
                else:
                    search_q = query if query.startswith("ytsearch:") else f"ytsearch:{query}"
                    info = ydl.extract_info(search_q, download=False)
                    if 'entries' in info: info = info['entries'][0]
                    return info
        except: return None

    def _start_player(self):
        """Inicia o reinicia el player de audio con SoundDevice"""
        try:
            with self._stream_lock:
                if self.stream_out is not None:
                    try: 
                        self.stream_out.stop()
                        self.stream_out.close()
                    except: 
                        pass
                    self.stream_out = None
            
            # Crear nuevo stream
            success = self._create_audio_stream()
            
            if not success:
                print("!! Error: No se pudo crear stream con SoundDevice")
                return
                
        except Exception as e:
            print(f"!! Error iniciando Player con SoundDevice: {e}")

    def _start_reader(self, stream_url):
        def reader():
            # ✅ USAR LA RUTA FFMPEG CORREGIDA
            ffmpeg_bin = self.ffmpeg_path
            
            # ✅ COMANDO OPTIMIZADO CON BUFFERS GRANDES
            command = [
                ffmpeg_bin, 
                "-reconnect", "1", 
                "-reconnect_streamed", "1", 
                "-reconnect_delay_max", "5", 
                "-i", stream_url, 
                "-acodec", "pcm_s16le", 
                "-ac", "2", 
                "-ar", "44100", 
                "-f", "s16le", 
                "-bufsize", "1024k",  # ✅ Buffer grande
                "-loglevel", "quiet", 
                "pipe:1"
            ]
            
            try:
                # Configuración para evitar ventana negra en Windows
                creation_flags = 0
                if sys.platform == "win32":
                    creation_flags = subprocess.CREATE_NO_WINDOW
                
                self.ffmpeg_process = subprocess.Popen(
                    command, 
                    stdout=subprocess.PIPE, 
                    stderr=subprocess.PIPE, 
                    bufsize=8192,  # ✅ Buffer de lectura grande
                    creationflags=creation_flags
                )
                
                # ✅ LEER EN BLOQUES MÁS GRANDES (8192 bytes)
                while self.ffmpeg_process and self.ffmpeg_process.poll() is None:
                    if self.stop_signal: break
                    data = self.ffmpeg_process.stdout.read(8192)  # ✅ 8192 en lugar de 4096
                    if not data: break
                    try: 
                        # ✅ Timeout más largo para buffers grandes
                        self.audio_data_queue.put(data, timeout=2.0)
                    except queue.Full: 
                        if self.stop_signal: break
                        # Si la cola está llena, esperar un poco
                        time.sleep(0.01)
                        continue
            except Exception as e:
                print(f"!! Error en reader: {e}")
            finally:
                if self.ffmpeg_process:
                    try: 
                        self.ffmpeg_process.kill()
                    except: 
                        pass
        self._reader_thread = threading.Thread(target=reader, daemon=True)
        self._reader_thread.start()

    def _cleanup_audio_resources(self):
        """Limpia todos los recursos de audio"""
        try: 
            if self.ffmpeg_process: 
                self.ffmpeg_process.kill()
                self.ffmpeg_process = None
        except: pass
        try:
            with self._stream_lock:
                if self.stream_out: 
                    try:
                        self.stream_out.stop()
                        self.stream_out.close()
                    except:
                        pass
                    finally:
                        self.stream_out = None
        except: pass
        with self.audio_data_queue.mutex: self.audio_data_queue.queue.clear()
        
        # Limpiar señales de cambio
        self._device_change_requested.clear()
        self._new_device_id = None
        self._new_device_name = None

    def pause(self, force=False):
        self.is_paused = True

    def resume(self, force=False):
        self.is_paused = False

    def toggle_pause(self):
        self.is_paused = not self.is_paused
        return self.is_paused

    def stop_audio(self, reset_data=True, silent=False):
        if not silent: 
            print(">> [SISTEMA] Parando audio...")
        
        self.stop_signal = True
        self.autoplay_enabled = False 
        
        with self.track_queue.mutex: 
            self.track_queue.queue.clear()
        
        if self.ffmpeg_process:
            try: 
                self.ffmpeg_process.kill()
            except: 
                pass
        
        time.sleep(0.05)
        self._cleanup_audio_resources()
        
        if reset_data:
            self.current_title = "Detenido"
            self.current_thumbnail = None
            self.is_paused = False

    def __del__(self):
        """Destructor para limpiar recursos"""
        self.running_device_monitor = False
        self.stop_audio(silent=True)
        # No hay necesidad de terminar sounddevice como con PyAudio