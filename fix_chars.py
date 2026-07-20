import os

replacements = {
    "â† ": "←",
    "â€”": "—",
    "âœ“": "✓",
    "âš ": "⚠",
    "Â©": "©",
    "âš¡": "⚡"
}

for root, dirs, files in os.walk(r"c:\Users\dvasa\QuizWebApplication\exam\templates"):
    for file in files:
        if file.endswith(".html"):
            path = os.path.join(root, file)
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            
            new_content = content
            for k, v in replacements.items():
                new_content = new_content.replace(k, v)
                
            if new_content != content:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(new_content)
                print(f"Fixed {path}")
