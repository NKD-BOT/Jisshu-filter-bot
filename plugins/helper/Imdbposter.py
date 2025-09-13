import aiohttp
import logging
from PIL import Image
from io import BytesIO

logger = logging.getLogger(__name__)

JISSHU_API = "https://jisshuapis.vercel.app/api.php?query="

async def get_movie_details(query: str) -> dict:
    """Fetch movie details from Jisshu API"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(JISSHU_API + query) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data and "title" in data:
                        return {
                            "title": data.get("title"),
                            "year": data.get("year"),
                            "rating": data.get("rating"),
                            "genres": data.get("genre"),
                            "poster_url": data.get("poster"),
                            "backdrop_url": data.get("backdrop"),
                            "url": data.get("imdb_url"),
                            "tmdb_url": data.get("tmdb_url")
                        }
    except Exception as e:
        logger.error(f"Jisshu API Error: {e}")
    return {"error": True}

async def get_movie_detailsx(query: str) -> dict:
    """
    Dummy TMDB fetcher for compatibility.
    If you don’t want TMDB, it will fallback to Jisshu.
    """
    return await get_movie_details(query)

async def fetch_image(url: str, size=(1280, 720)) -> BytesIO:
    """Download and resize poster/backdrop"""
    if not url:
        return None
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status == 200:
                    img_data = await resp.read()
                    img = Image.open(BytesIO(img_data))
                    img = img.resize(size, Image.Resampling.LANCZOS)
                    output = BytesIO()
                    output.name = "poster.jpg"
                    img.save(output, format="JPEG")
                    output.seek(0)
                    return output
    except Exception as e:
        logger.error(f"Image fetch/resize failed: {e}")
    return None
