import os
import urllib.request
import zipfile
import re

STATIC_DIR = os.path.join("exam", "static")
JS_DIR = os.path.join(STATIC_DIR, "js", "vendor")
FONTS_DIR = os.path.join(STATIC_DIR, "fonts")
CSS_DIR = os.path.join(STATIC_DIR, "css")

os.makedirs(JS_DIR, exist_ok=True)
os.makedirs(FONTS_DIR, exist_ok=True)
os.makedirs(CSS_DIR, exist_ok=True)

print("Downloading Chart.js...")
urllib.request.urlretrieve("https://cdn.jsdelivr.net/npm/chart.js", os.path.join(JS_DIR, "chart.min.js"))

print("Downloading Chart.js DataLabels...")
urllib.request.urlretrieve("https://cdn.jsdelivr.net/npm/chartjs-plugin-datalabels@2", os.path.join(JS_DIR, "chartjs-plugin-datalabels.min.js"))

print("Downloading Sortable.js...")
urllib.request.urlretrieve("https://cdn.jsdelivr.net/npm/sortablejs@latest/Sortable.min.js", os.path.join(JS_DIR, "Sortable.min.js"))

print("Downloading TinyMCE...")
tinymce_zip = os.path.join(JS_DIR, "tinymce.zip")
urllib.request.urlretrieve("https://download.tiny.cloud/tinymce/community/tinymce_6.8.2.zip", tinymce_zip)
with zipfile.ZipFile(tinymce_zip, 'r') as zip_ref:
    zip_ref.extractall(JS_DIR)
os.remove(tinymce_zip)
print("Extracted TinyMCE.")

def download_font(name, url):
    print(f"Downloading font {name}...")
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'})
    try:
        with urllib.request.urlopen(req) as response:
            css_content = response.read().decode('utf-8')
            
            # Find all url() links
            urls = re.findall(r'url\((.*?)\)', css_content)
            for i, font_url in enumerate(urls):
                font_url = font_url.strip('"\'')
                filename = f"{name}_{i}.woff2"
                urllib.request.urlretrieve(font_url, os.path.join(FONTS_DIR, filename))
                css_content = css_content.replace(font_url, f"../fonts/{filename}")
            
            with open(os.path.join(CSS_DIR, f"{name}.css"), "w") as f:
                f.write(css_content)
    except Exception as e:
        print(f"Error downloading {name}: {e}")

download_font("google_fonts_inter_outfit", "https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&family=Outfit:wght@500;600;700;800&display=swap")
download_font("google_fonts_orbitron", "https://fonts.googleapis.com/css2?family=Orbitron:wght@400;600&display=swap")

print("Done.")
