from weather_images import WeatherImagesClient
from telegram_notifier import TelegramNotifier

client = WeatherImagesClient()
notifier = TelegramNotifier()

print("Gerando pacote completo de imagens meteorologicas...")
images = client.get_weather_update_package()

captions = {
    "radar_gif": "Radar IPMET (GIF animado)",
    "satelite_gif": "Satelite IPMET (GIF animado)",
    "sigwx": "SIGWX Inferior (SUP - FL250)\nFenomenos significativos para helicopteros",
    "indice_k": "Indice K - Potencial de Tempestades\nK > 30: Alta probabilidade\nK > 35: Tempestades severas",
    "ventos_850": "Ventos em 850 hPa (~1500m)\nAltitude de cruzeiro helicopteros",
    "radar": "Radar Windy - Regiao SP",
    "satelite": "Satelite GOES-16 (NOAA) - Geocolor",
    "nuvens": "Infravermelho GOES-16 (NOAA) - Nuvens",
    "webcam_sbgr": "Webcam SBGR - Guarulhos ao vivo",
}

print(f"\nEnviando {len([v for v in images.values() if v])} imagens...\n")

for key, filepath in images.items():
    if filepath:
        caption = captions.get(key, key)
        print(f"Enviando {key}...")
        notifier.send_photo(filepath, caption)

print("\nPacote completo enviado!")
