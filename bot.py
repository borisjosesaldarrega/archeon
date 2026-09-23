import discord
from discord.ext import commands
import yt_dlp as youtube_dl
import asyncio
import os
from dotenv import load_dotenv
import google.generativeai as genai
import traceback
import logging
import re

# Define la expresión regular al inicio del código (fuera de la función)
URL_REGEX = re.compile(r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+')

# Configuración inicial
logging.basicConfig(level=logging.WARNING) 
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Confirmacion de key
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

#FUNCIONES DEL BOT NECESARIAS
chat_histories = {}
MAX_HISTORY = 10  
saved_playlists = {}  
queues = {}
current_song = None
loop_mode = {}


# Configuración de la IA
genai.configure(api_key=GOOGLE_API_KEY)
model = genai.GenerativeModel("gemini-2.0-flash")  

# Configuración del bot
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='¡', intents=intents)


# --------------------------
# Módulo de Música
# --------------------------

#configuracion glbal de FFmpeg
FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -loglevel warning',
    'options': '-vn -c:a libopus -b:a 128k -ar 48000 -ac 2 -filter:a "volume=0.8"',
    'executable': 'ffmpeg'
}

# Opciones para youtube_dl
ydl_opts = {
    'format': 'bestaudio/best',
    'default_search': 'ytsearch',
    'noplaylist': True,
    'quiet': True,
    'no_warnings': True,
    'ignoreerrors': True,
    'extract_flat': False,
    'postprocessors': [{
        'key': 'FFmpegExtractAudio',
        'preferredcodec': 'opus',
        'preferredquality': '192',
    }],
    'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'nocheckcertificate': True,
    'source_address': '0.0.0.0'
}



async def check_queue(ctx):
    """Versión corregida como corrutina"""
    if queues.get(ctx.guild.id) and queues[ctx.guild.id]:  # Corregido: queues en lugar de queue
        next_song = queues[ctx.guild.id].pop(0)
        
        try:
            source = await discord.FFmpegOpusAudio.from_probe(
                next_song['url'],
                method='fallback',
                **FFMPEG_OPTIONS
            )
            
            global current_song
            current_song = next_song
            
            ctx.voice_client.play(
                source,
                after=lambda e: asyncio.run_coroutine_threadsafe(
                    check_queue(ctx), 
                    bot.loop
                ) if e is None else print(f'Error: {e}')
            )
            
            embed = discord.Embed(
                title="🎵 Reproduciendo ahora (desde cola)",
                description=f"[{current_song['title']}]({current_song['web_url']})",
                color=discord.Color.blurple()
            )
            
            if current_song['duration'] > 0:
                mins, secs = divmod(current_song['duration'], 60)
                embed.add_field(name="Duración", value=f"{mins}:{secs:02d}")
            
            embed.set_thumbnail(url=current_song['thumbnail'])
            embed.set_footer(text=f"Solicitado por {current_song['requested_by'].display_name}")
            
            await ctx.send(embed=embed)
            
        except Exception as e:
            print(f"Error en check_queue: {e}")
            await ctx.send("⚠️ Error al pasar a la siguiente canción")
            
        
@bot.command(name='join', help='Hace que el bot se una al canal de voz')
async def join(ctx):
    if ctx.author.voice is None:
        await ctx.send("¡No estás en un canal de voz!")
        return
    
    channel = ctx.author.voice.channel
    if ctx.voice_client is None:
        await channel.connect()
    else:
        await ctx.voice_client.move_to(channel)

@bot.command(name='play')
async def play(ctx, *, busqueda: str):
    is_url = bool(URL_REGEX.match(busqueda))
    
    if not ctx.author.voice:
        return await ctx.send("¡No estás en un canal de voz!")
    
    voice_client = ctx.voice_client or await ctx.author.voice.channel.connect()
    
    with youtube_dl.YoutubeDL(ydl_opts) as ydl:
        try:
            # Extraer información del audio
            info = ydl.extract_info(
            busqueda if is_url else f"ytsearch:{busqueda}",
            download=False
        )
            
            # Si es una búsqueda, tomar el primer resultado
            if 'entries' in info:
                info = info['entries'][0]
            
            # Obtener la URL de audio directamente
            if 'url' in info:
                url2 = info['url']
            else:
                # Buscar el mejor formato de audio
                format = next(
                    (f for f in info['formats'] 
                    if f.get('acodec') != 'none'),
                    info['formats'][0]
                )
                url2 = format['url']
            
            # Configuración de FFmpeg
            FFMPEG_OPTIONS = {
                'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -loglevel warning',
                'options': '-vn -c:a libopus -b:a 128k -ar 48000 -ac 2 -filter:a "volume=0.8"',
                'executable': 'ffmpeg'
            }
            
            # Crear objeto canción completo para la cola
            song = {
                'title': info.get('title', busqueda),
                'url': url2,
                'web_url': info.get('webpage_url', busqueda),
                'duration': info.get('duration', 0),
                'requested_by': ctx.author,
                'thumbnail': info.get('thumbnail', '')
            }
            
            # Si ya hay música reproduciéndose, añadir a la cola
            if voice_client.is_playing() or voice_client.is_paused():
                if ctx.guild.id not in queues:
                    queues[ctx.guild.id] = []
                queues[ctx.guild.id].append(song)
                
                embed = discord.Embed(
                    title="🎵 Añadido a la cola",
                    description=f"[{song['title']}]({song['web_url']})",
                    color=discord.Color.green()
                )
                embed.add_field(name="Posición en cola", value=str(len(queues[ctx.guild.id])))
                embed.set_thumbnail(url=song['thumbnail'])
                embed.set_footer(text=f"Solicitado por {ctx.author.display_name}")
                return await ctx.send(embed=embed)
            
            # Si no hay música reproduciéndose, crear fuente y reproducir
            source = await discord.FFmpegOpusAudio.from_probe(
                url2,
                method='fallback',
                **FFMPEG_OPTIONS
            )
            
            # Actualizar estado global
            global current_song
            current_song = song
            
            # Reproducir
            voice_client.play(
                source, 
                after=lambda e: asyncio.run_coroutine_threadsafe(
                    check_queue(ctx), 
                    bot.loop
                ) if e is None else print(f'Error: {e}')
            )
            
            # Mostrar embed
            embed = discord.Embed(
                title="🎵 Reproduciendo ahora",
                description=f"[{current_song['title']}]({current_song['web_url']})",
                color=discord.Color.blurple()
            )
            duration = current_song['duration']
            embed.add_field(name="Duración", value=f"{duration//60}:{duration%60:02d}" if duration else "Desconocida")
            embed.set_thumbnail(url=current_song['thumbnail'])
            embed.set_footer(text=f"Solicitado por {ctx.author.display_name}")
            
            await ctx.send(embed=embed)
            
        except Exception as e:
            error_msg = f"❌ Error al reproducir: {str(e)}"
            if "formats" in str(e):
                error_msg += "\n⚠️ Problema al obtener formatos de audio. Intenta con otro video."
            await ctx.send(error_msg[:2000])
            import traceback
            traceback.print_exc()
            
@bot.command(name='skip')
async def skip(ctx):
    """Salta la canción actual y pasa a la siguiente en la cola."""
    voice = ctx.voice_client
    
    if not voice or not voice.is_playing():
        await ctx.send("⚠️ No hay música reproduciéndose.")
        return
    
    voice.stop()  # Esto activará automáticamente el callback `after` (que llama a check_queue)
    await ctx.send("⏭️ Canción saltada")
    
@bot.command(name='pause')
async def pause(ctx):
    """Pausar la música"""
    voice = ctx.voice_client
    if voice and voice.is_playing():
        voice.pause()
        await ctx.send("⏸️ Música pausada")
    else:
        await ctx.send("⚠️ No hay música reproduciéndose")

@bot.command(name='resume')
async def resume(ctx):
    """Reanudar la música"""
    voice = ctx.voice_client
    if voice and voice.is_paused():
        voice.resume()
        await ctx.send("▶️ Música reanudada")
    else:
        await ctx.send("⚠️ La música no está pausada")

@bot.command(name='lista')
async def queue(ctx):
    """Mostrar la cola de reproducción"""
    guild_id = ctx.guild.id
    if not queues.get(guild_id) and not current_song:
        await ctx.send("📭 La cola está vacía")
    else:
        embed = discord.Embed(title="🎶 Cola de reproducción", color=discord.Color.purple())
        
        if current_song:
            duration = ""
            if current_song['duration'] > 0:
                mins, secs = divmod(current_song['duration'], 60)
                duration = f" [{mins}:{secs:02d}]"
            
            embed.add_field(
                name="🔊 Reproduciendo ahora",
                value=f"**{current_song['title']}**{duration}\nSolicitado por: {current_song['requested_by'].mention}",
                inline=False
            )
        
        if queues.get(guild_id):
            for i, item in enumerate(queues[guild_id][:10]):
                embed.add_field(name=f"{i+1}.", value=item['title'], inline=False)
            
            if len(queues[guild_id]) > 10:
                embed.set_footer(text=f"Y {len(queues[guild_id])-10} canciones más en la cola...")
        
        await ctx.send(embed=embed)

@bot.command(name='disconnect')
async def disconnect(ctx):
    """Desconecta al bot del canal de voz"""
    if ctx.voice_client:
        await ctx.voice_client.disconnect()
        await ctx.send("Desconectado del canal de voz")
    else:
        await ctx.send("No estoy conectado a ningún canal de voz")
        
@bot.command(name='shuffle')
async def shuffle_queue(ctx):
    if ctx.guild.id not in queues or len(queues[ctx.guild.id]) < 2:
        return await ctx.send("🔀 Necesitas al menos 2 canciones en la cola para mezclar.")
    
    import random
    random.shuffle(queues[ctx.guild.id])
    await ctx.send("🔀 Cola mezclada aleatoriamente.")

@bot.command(name='remove')
async def remove_song(ctx, index: int):
    if ctx.guild.id not in queues or index < 1 or index > len(queues[ctx.guild.id]):
        return await ctx.send("❌ Índice inválido o cola vacía.")
    
    removed = queues[ctx.guild.id].pop(index - 1)
    await ctx.send(f"🗑️ Canción **{removed['title']}** eliminada de la cola.")

@bot.command(name='volume')
async def volume(ctx, vol: int = None):
    if not vol:
        current_vol = 80  # Valor por defecto (0.8)
        if ctx.voice_client and ctx.voice_client.source:
            if hasattr(ctx.voice_client.source, 'volume'):
                current_vol = int(ctx.voice_client.source.volume * 100)
        return await ctx.send(f"🔊 Volumen actual: **{current_vol}%**")
    
    if vol < 0 or vol > 200:
        return await ctx.send("❌ El volumen debe estar entre 0 y 200%.")
    
    # Ajustar el volumen de la canción actual (si hay una)
    if ctx.voice_client and ctx.voice_client.source:
        if hasattr(ctx.voice_client.source, 'volume'):
            ctx.voice_client.source.volume = vol / 100
    
    # Actualizar FFMPEG_OPTIONS para futuras canciones
    FFMPEG_OPTIONS['options'] = FFMPEG_OPTIONS['options'].replace(
        'volume=0.8', f'volume={vol/100}'
    )
    
    await ctx.send(f"🔊 Volumen ajustado a **{vol}%**")
    
@bot.command(name='borrar_cola')
async def clear_queue(ctx):
    if ctx.guild.id in queues and queues[ctx.guild.id]:
        queues[ctx.guild.id].clear()
        await ctx.send("🗑️ Cola de reproducción borrada.")
    else:
        await ctx.send("📭 La cola ya está vacía.")

@bot.command(name='stop', aliases=['parar'])
async def stop(ctx):
    """Detiene la música y limpia la cola"""
    voice = ctx.voice_client
    
    if not voice or not voice.is_playing():
        return await ctx.send("⚠️ No hay música reproduciéndose")
    
    # Limpiar la cola primero
    if ctx.guild.id in queues:
        queues[ctx.guild.id].clear()
    
    # Detener la reproducción
    voice.stop()
    
    # Resetear la canción actual
    global current_song
    current_song = None
    
    await ctx.send("⏹️ Música detenida y cola limpiada")

@bot.command(name='playtop')
async def playtop(ctx, *, busqueda: str):
    # Primero obtenemos la canción igual que en el comando play normal
    is_url = bool(URL_REGEX.match(busqueda))
    
    if not ctx.author.voice:
        return await ctx.send("¡No estás en un canal de voz!")
    
    voice_client = ctx.voice_client or await ctx.author.voice.channel.connect()
    
    with youtube_dl.YoutubeDL(ydl_opts) as ydl:
        try:
            info = ydl.extract_info(
                busqueda if is_url else f"ytsearch:{busqueda}",
                download=False
            )
            
            if 'entries' in info:
                info = info['entries'][0]
            
            if 'url' in info:
                url2 = info['url']
            else:
                format = next(
                    (f for f in info['formats'] 
                    if f.get('acodec') != 'none'),
                    info['formats'][0]
                )
                url2 = format['url']
            
            song = {
                'title': info.get('title', busqueda),
                'url': url2,
                'web_url': info.get('webpage_url', busqueda),
                'duration': info.get('duration', 0),
                'requested_by': ctx.author,
                'thumbnail': info.get('thumbnail', '')
            }
            
            if ctx.guild.id not in queues:
                queues[ctx.guild.id] = []
                
            # Añadir al principio de la cola
            queues[ctx.guild.id].insert(0, song)
            
            # Si no hay nada reproduciéndose, iniciar reproducción
            if not voice_client.is_playing() and not voice_client.is_paused():
                await check_queue(ctx)
                return
            
            await ctx.send(f"⏫ Canción añadida al inicio de la cola: **{song['title']}**")
            
        except Exception as e:
            await ctx.send(f"❌ Error: {str(e)[:200]}")
            
@bot.command(name='save')
async def save_playlist(ctx, nombre: str):
    if not queues.get(ctx.guild.id):
        return await ctx.send("❌ No hay canciones en la cola para guardar.")
    
    if ctx.guild.id not in saved_playlists:
        saved_playlists[ctx.guild.id] = {}
    
    saved_playlists[ctx.guild.id][nombre] = queues[ctx.guild.id].copy()
    await ctx.send(f"💾 Playlist guardada como **{nombre}**.")

@bot.command(name='cargar')
async def cargar_playlist(ctx, nombre: str):
    """Carga una playlist guardada a la cola actual"""
    if ctx.guild.id not in saved_playlists or nombre not in saved_playlists[ctx.guild.id]:
        return await ctx.send(f"❌ No existe la playlist '{nombre}'")
    
    if ctx.guild.id not in queues:
        queues[ctx.guild.id] = []
    
    queues[ctx.guild.id].extend(saved_playlists[ctx.guild.id][nombre])
    await ctx.send(f"🎵 Playlist '{nombre}' cargada ({len(saved_playlists[ctx.guild.id][nombre])} canciones)")

@bot.command(name='listar_playlists')
async def listar_playlists(ctx):
    """Muestra todas las playlists guardadas"""
    if ctx.guild.id not in saved_playlists or not saved_playlists[ctx.guild.id]:
        return await ctx.send("📭 No hay playlists guardadas")
    
    embed = discord.Embed(title="📋 Playlists Guardadas", color=discord.Color.blue())
    for nombre, canciones in saved_playlists[ctx.guild.id].items():
        embed.add_field(name=nombre, value=f"{len(canciones)} canciones", inline=False)
    
    await ctx.send(embed=embed)
    
# --------------------------
# Módulo de IA 
# --------------------------

@bot.command()  
async def charla(ctx, *, mensaje: str):
    """Interactúa con la IA de Google Gemini con memoria contextual mejorada."""
    user_id = str(ctx.author.id)
    
    # Respuestas rápidas
    quick_responses = {
        "¿cómo te llamas?": "🤖 ¡Soy Archeon, tu asistente de Discord! ✨",
        "¿quién eres?": "🤖 ¡Soy Archeon, tu asistente de Discord! ✨",
        "¿cuál es tu nombre?": "🤖 ¡Soy Archeon, tu asistente de Discord! ✨",
        "¿quién soy?": f"🤖 ¡Claro que te conozco, {ctx.author.mention}! Eres {ctx.author.name} 😊",
        "¿cómo me llamo?": f"🤖 ¡Claro que te conozco, {ctx.author.mention}! Eres {ctx.author.name} 😊",
        "¿me conoces?": f"🤖 ¡Claro que te conozco, {ctx.author.mention}! Eres {ctx.author.name} 😊"
    }
    
    lower_msg = mensaje.lower().strip()
    if lower_msg in quick_responses:
        return await ctx.send(quick_responses[lower_msg])

    try:
        # Inicializar historial si es nuevo usuario
        if user_id not in chat_histories:
            chat_histories[user_id] = []
                
        # Construir contexto
        context = {
            "historial": "\n".join(chat_histories[user_id][-MAX_HISTORY:]),
            "nuevo_mensaje": mensaje,
            "usuario": ctx.author.name
        }
        
        prompt = (
            "Eres un asistente de Discord llamado Archeon. "
            "Aquí está el historial de conversación reciente:\n"
            "{historial}\n\n"
            "Nuevo mensaje de {usuario}: {nuevo_mensaje}\n\n"
            "Responde de manera concisa y amigable."
        ).format(**context)
        
        # Generar respuesta
        response = model.generate_content(prompt)
        respuesta = response.text.strip()
        
        # Actualizar historial
        chat_histories[user_id].extend([
            f"{ctx.author.name}: {mensaje}",
            f"Archeon: {respuesta}"
        ])
        chat_histories[user_id] = chat_histories[user_id][-MAX_HISTORY:]
        
        # Enviar respuesta
        await ctx.send(f"{ctx.author.mention} {respuesta}")
        
    except genai.errors.GoogleAPIError as api_error:
        await ctx.send("🔴 Error con la API de Google. Por favor, reporta esto al administrador.")
        logger.error(f"Google API Error: {api_error}")
        
    except asyncio.TimeoutError:
        await ctx.send("⏱️ La IA tardó demasiado en responder. Intenta nuevamente.")
        
    except Exception as e:
        logger.error(f"Error inesperado: {e}", exc_info=True)
        await ctx.send("⚠️ Ocurrió un error inesperado. Por favor, intenta nuevamente más tarde.")
        
        
@bot.command()
async def olvidar(ctx):
    """Reinicia el historial de conversación contigo"""
    user_id = str(ctx.author.id)
    if user_id in chat_histories:
        chat_histories[user_id] = []
    await ctx.send("🔄 ¡He reiniciado nuestra conversación! ¿En qué puedo ayudarte ahora?")
        
# ------------------------------------------
# Módulo de IA para separar por llamadas
# ------------------------------------------

@bot.command(name='separar', aliases=['gamevoice'])
async def separar_jugadores(ctx):
    """Separa a los usuarios en canales de voz según el juego que están jugando"""
    try:
        # Verificar que el comando se ejecuta en un servidor
        if not ctx.guild:
            await ctx.send("❌ Este comando solo funciona en servidores.")
            return

        # Verificar que el usuario está en un canal de voz
        if not ctx.author.voice or not ctx.author.voice.channel:
            await ctx.send("❌ Debes estar en un canal de voz para usar este comando.")
            return

        voice_channel = ctx.author.voice.channel
        members = voice_channel.members

        # Obtener los juegos activos entre los miembros
        juegos_activos = {}
        for member in members:
            if member.activity and member.activity.type == discord.ActivityType.playing:
                juego = member.activity.name
                if juego not in juegos_activos:
                    juegos_activos[juego] = []
                juegos_activos[juego].append(member)

        # Si no hay suficientes juegos diferentes
        if len(juegos_activos) < 2:
            await ctx.send("🔍 No hay suficientes juegos diferentes para separar (se necesitan al menos 2).")
            return

        # Consultar a la IA para nombres creativos de canales
        prompt = (
            f"Dame nombres creativos para canales de Discord basados en estos juegos: {', '.join(juegos_activos.keys())}. "
            "Los nombres deben ser cortos, relevantes al juego y entre 3-5 palabras. "
            "Formato: Juego: Nombre sugerido (uno por juego)"
        )

        try:
            response = model.generate_content(prompt)
            nombres_canales = {}
            
            # Parsear la respuesta de la IA
            for line in response.text.split('\n'):
                if ':' in line:
                    juego, nombre = line.split(':', 1)
                    juego = juego.strip()
                    nombre = nombre.strip()
                    if juego in juegos_activos:
                        nombres_canales[juego] = nombre
        except Exception as e:
            logging.error(f"Error al generar nombres con IA: {str(e)}")
            # Usar nombres por defecto si falla la IA
            nombres_canales = {juego: f"🎮 {juego}" for juego in juegos_activos}

        # Crear categoría temporal si no existe
        categoria = discord.utils.get(ctx.guild.categories, name="Juegos Temporales")
        if not categoria:
            categoria = await ctx.guild.create_category_channel("Juegos Temporales")

        # Crear canales de voz temporales
        canales_creados = {}
        for juego, nombre in nombres_canales.items():
            try:
                # Limitar longitud del nombre a 100 caracteres (límite de Discord)
                nombre_canal = nombre[:100]
                new_channel = await ctx.guild.create_voice_channel(
                    name=nombre_canal,
                    category=categoria,
                    reason=f"Separación automática por juego: {juego}"
                )
                canales_creados[juego] = new_channel
            except Exception as e:
                logging.error(f"Error al crear canal para {juego}: {str(e)}")
                continue

        # Mover usuarios a los canales correspondientes
        movimientos = {}
        for juego, miembros in juegos_activos.items():
            if juego in canales_creados:
                canal_destino = canales_creados[juego]
                for miembro in miembros:
                    try:
                        await miembro.move_to(canal_destino)
                        if juego not in movimientos:
                            movimientos[juego] = 0
                        movimientos[juego] += 1
                    except Exception as e:
                        logging.error(f"Error al mover {miembro.display_name}: {str(e)}")

        # Enviar resumen
        resumen = "✅ Separación completada:\n"
        for juego, count in movimientos.items():
            resumen += f"- {juego}: {count} jugadores movidos a {canales_creados[juego].mention}\n"

        await ctx.send(resumen)

        # Programar eliminación de canales después de inactividad
        await asyncio.sleep(300)  # Esperar 5 minutos

        # Verificar si los canales están vacíos
        for juego, canal in canales_creados.items():
            if len(canal.members) == 0:
                try:
                    await canal.delete(reason="Canal temporal de juego vacío")
                except Exception as e:
                    logging.error(f"Error al eliminar canal {canal.name}: {str(e)}")

    except Exception as e:
        logging.error(f"Error en comando separar: {str(e)}\n{traceback.format_exc()}")
        await ctx.send("❌ Ocurrió un error al procesar el comando. Por favor intenta nuevamente.")

# --------------------------
# Utilidades
# --------------------------

@bot.command(name="votar")
async def votar(ctx, *args):
    """Crea encuestas con o sin tiempo personalizado.
    Uso 1: ¡votar "¿Pregunta?" op1 op2 (1 minuto por defecto)
    Uso 2: ¡votar 5 "¿Pregunta?" op1 op2 (5 minutos)"""
    
    # Configuración inicial
    tiempo_minutos = 1  # Valor por defecto
    pregunta = ""
    opciones = []
    emojis = ['1️⃣', '2️⃣', '3️⃣', '4️⃣', '5️⃣', '6️⃣']

    # Procesar argumentos
    try:
        # Caso 1: ¡votar "pregunta" op1 op2
        if not args[0].isdigit():
            pregunta = args[0]
            opciones = list(args[1:])
        
        # Caso 2: ¡votar 5 "pregunta" op1 op2
        else:
            tiempo_minutos = int(args[0])
            pregunta = args[1]
            opciones = list(args[2:])
            
        # Validaciones
        if len(opciones) < 2:
            return await ctx.send("❌ Necesitas al menos 2 opciones.")
        if len(opciones) > 6:
            return await ctx.send("⚠️ Máximo 6 opciones permitidas.")
        if tiempo_minutos <= 0:
            return await ctx.send("❌ El tiempo debe ser mayor a 0 minutos.")

    except IndexError:
        return await ctx.send("❌ Formato incorrecto. Ejemplos:\n"
                            "`¡votar \"¿Pregunta?\" op1 op2`\n"
                            "`¡votar 3 \"¿Pregunta?\" op1 op2`")

    # Crear embed
    embed = discord.Embed(
        title=f"📊 {pregunta}",
        description="\n".join([f"{emojis[i]} {op}" for i, op in enumerate(opciones)]),
        color=discord.Color.gold()
    )
    embed.set_footer(text=f"⏳ Votación abierta por {tiempo_minutos} minuto(s)")

    # Enviar y añadir reacciones
    mensaje = await ctx.send(embed=embed)
    for i in range(len(opciones)):
        await mensaje.add_reaction(emojis[i])

    # Esperar y calcular resultados
    await asyncio.sleep(tiempo_minutos * 60)
    mensaje_actualizado = await ctx.channel.fetch_message(mensaje.id)
    
    resultados = {}
    for i, emoji in enumerate(emojis[:len(opciones)]):
        for reaccion in mensaje_actualizado.reactions:
            if str(reaccion.emoji) == emoji:
                resultados[opciones[i]] = reaccion.count - 1

    # Determinar ganador
    if not resultados:
        return await ctx.send("🤷 Nadie votó.")

    ganador = max(resultados.items(), key=lambda x: x[1])
    porcentaje = (ganador[1] / sum(resultados.values())) * 100

    # Generar comentario con IA
    try:
        respuesta = model.generate_content(
            f"Crea un comentario gracioso (1 línea) sobre esta votación: "
            f"'{pregunta}'. Ganador: '{ganador[0]}' con {porcentaje:.1f}% votos."
        )
        comentario = respuesta.text
    except Exception:
        comentario = "¡Y el veredicto es...!"

    # Mostrar resultados
    embed_resultado = discord.Embed(
        title=f"🎉 Ganador: {ganador[0]} ({porcentaje:.1f}%)",
        description=f"**{pregunta}**\n\n{comentario}",
        color=discord.Color.green()
    )
    await ctx.send(embed=embed_resultado)
#
# Ideas del bot
#

@bot.command(name='limpiar')
@commands.has_permissions(manage_messages=True)
async def limpiar(ctx, cantidad: int = 10):
    """Elimina mensajes (máx 100)"""
    if 1 <= cantidad <= 100:
        await ctx.channel.purge(limit=cantidad + 1)
        msg = await ctx.send(f"🧹 Eliminados {cantidad} mensajes", delete_after=5)
    else:
        await ctx.send("❌ Cantidad inválida (1-100)", delete_after=5)

@bot.command(name='silenciar')
@commands.has_permissions(kick_members=True)
async def silenciar(ctx, miembro: discord.Member, *, razón: str = "Sin razón"):
    """Silencia a un usuario"""
    role = discord.utils.get(ctx.guild.roles, name="Silenciado")
    if not role:
        role = await ctx.guild.create_role(name="Silenciado")
        for channel in ctx.guild.channels:
            await channel.set_permissions(role, send_messages=False)
    
    await miembro.add_roles(role)
    embed = discord.Embed(
        title=f"🔇 {miembro.display_name} silenciado",
        description=f"Razón: {razón}",
        color=discord.Color.red()
    )
    await ctx.send(embed=embed)
    
@bot.command(name='ticket')
async def crear_ticket(ctx, *, motivo: str = "Sin motivo especificado"):
    """Sistema confidencial de tickets por DM"""
    ADMIN_ID = 607681770422534144  
    
    try:
        # 1. Borrar inmediatamente el mensaje del usuario
        try:
            await ctx.message.delete()
        except:
            pass

        # 2. Enviar confirmación temporal al usuario
        confirmacion = await ctx.send(f"{ctx.author.mention} 📩 Ticket recibido, procesando...", delete_after=5)

        # 3. Crear embed del ticket
        embed = discord.Embed(
            title="🚨 TICKET CONFIDENCIAL",
            description=(
                f"**Usuario:** {ctx.author.mention} (`{ctx.author.id}`)\n"
                f"**Servidor:** `{ctx.guild.name}`\n"
                f"**Canal:** <#{ctx.channel.id}>\n"
                f"**Motivo:** {motivo}\n"
                f"**Hora:** {ctx.message.created_at.strftime('%d/%m %H:%M')}"
            ),
            color=0xFF0000
        )
        embed.set_footer(text="Reacciona con 🔒 para confirmar lectura")

        # 4. Enviar DM al admin (tú)
        try:
            admin = await bot.fetch_user(ADMIN_ID)
            ticket_msg = await admin.send(embed=embed)  # Este es el mensaje IMPORTANTE que debes recibir
            await ticket_msg.add_reaction('🔒')
            
            # 5. Enviar confirmación final al usuario (por DM)
            try:
                await ctx.author.send(
                    "📬 **Ticket recibido**\n"
                    f"Motivo: {motivo}\n\n"
                    "Un administrador te responderá pronto por este medio.\n"
                    "⚠️ Por favor no elimines este mensaje."
                )
            except:
                await ctx.send(f"{ctx.author.mention} No pude enviarte DM. Por favor activa tus mensajes directos.", delete_after=15)
                
        except discord.Forbidden:
            await ctx.send(f"{ctx.author.mention} ❌ No pude notificar al soporte", delete_after=10)
            
    except Exception as e:
        print(f"Error en ticket: {traceback.format_exc()}")
        try:
            await ctx.author.send("❌ Error al procesar tu ticket")
        except:
            pass

@bot.event
async def on_raw_reaction_add(payload):
    # Verificar que es el emoji 🔒 en un DM
    if str(payload.emoji) == '🔒' and payload.guild_id is None:
        try:
            channel = await bot.fetch_channel(payload.channel_id)
            message = await channel.fetch_message(payload.message_id)
            
            # Verificar que es un mensaje de ticket y que lo reaccionaste tú
            if message.embeds and "🚨 TICKET CONFIDENCIAL" in message.embeds[0].title:
                if payload.user_id == 607681770422534144:  # Tu ID
                    embed = message.embeds[0]
                    
                    # Extraer ID del usuario - MÉTODO MEJORADO
                    description = embed.description
                    user_match = re.search(r'<@(\d+)>', description)  # Busca el ID entre <@ y >
                    
                    if user_match:
                        user_id = int(user_match.group(1))
                        
                        # Notificar al usuario
                        try:
                            user = await bot.fetch_user(user_id)
                            await user.send(
                                "🔔 **Notificación de soporte**\n"
                                "Hemos recibido tu ticket y lo estamos revisando.\n"
                                "Gracias por tu paciencia."
                            )
                        except Exception as user_error:
                            print(f"No se pudo notificar al usuario {user_id}: {user_error}")
                    else:
                        print("No se encontró ID de usuario en el embed")
        except Exception as e:
            print(f"Error en reacción de ticket: {traceback.format_exc()}")

#---------------
# ayuda
# ---------------
@bot.command(name="ayuda")
async def mostrar_ayuda(ctx):
    """Mostrar un menú con los comandos disponibles."""
    prefix = "¡"

    embed = discord.Embed(
        title="📖 Comandos disponibles",
        description="Aquí tienes una lista completa de comandos:",
        color=discord.Color.blurple()
    )

    embed.add_field(
        name="🎵 Música",
        value=(
            f"`{prefix}play [url/búsqueda]` - Reproduce música\n"
            f"`{prefix}pause` - Pausa la música\n"
            f"`{prefix}resume` - Reanuda\n"
            f"`{prefix}skip` - Salta la canción\n"
            f"`{prefix}stop` - Detiene y limpia la cola\n"
            f"`{prefix}lista` - Muestra la cola\n"
            f"`{prefix}shuffle` - Mezcla la cola\n"
            f"`{prefix}remove [posición]` - Elimina una canción\n"
            f"`{prefix}volume [0-200]` - Ajusta el volumen\n"
            f"`{prefix}playtop [url/búsqueda]` - Añade al inicio\n"
            f"`{prefix}borrar_cola` - Limpia la cola\n"
            f"`{prefix}save [nombre]` - Guarda la cola como playlist\n"
            f"`{prefix}disconnect` - Desconecta al bot"
        ),
        inline=False
    )

    embed.add_field(
        name="🧠 IA",
        value=(
            f"`{prefix}charla [mensaje]` - Chatea con la IA\n"
            f"`{prefix}olvidar` - Reinicia la conversación"
        ),
        inline=False
    )

    embed.add_field(
        name="🎮 Juegos",
        value=(
            f"`{prefix}separar` o `{prefix}gamevoice`\n"
            "Separa jugadores por juego"
        ),
        inline=False
    )

    embed.add_field(
        name="📊 Utilidades",
        value=(
            f"`{prefix}votar [tiempo] \"pregunta\" op1 op2`\n"
            "Crea encuestas con tiempo opcional (ej: `¡votar 5 \"¿Pizza?\" Sí No`)\n"
            f"`{prefix}votar \"pregunta\" op1 op2` - 1 minuto por defecto\n"
            "📌 Máx. 6 opciones | 🎉 Muestra resultados automáticos"
        ),
        inline=False
    )
    
    embed.add_field(
    name="🎫 Tickets",
    value=(f"`{prefix}ticket [motivo]`"),
        inline=False
    )

    embed.set_footer(text=f"Prefijo: '{prefix}' • Usa comillas para frases largas")
    await ctx.send(embed=embed)



@bot.event
async def on_ready():
    print(f'Bot conectado como {bot.user.name}')
    await bot.change_presence(activity=discord.Game(name="¡ayuda para comandos"))
@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return
    logger.error(f'Error en comando {ctx.command}: {error}')
    await ctx.send(f'⚠️ Ocurrió un error: {str(error)}')
@bot.event
async def on_ready():
    await bot.tree.sync()  
bot.run(TOKEN)