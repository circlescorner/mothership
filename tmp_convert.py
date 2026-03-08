with open("tmp_devplane_logs.txt", "rb") as f:
    text = f.read().decode("utf-16le")

with open("tmp_devplane_logs_utf8.txt", "w", encoding="utf-8") as f:
    f.write(text)
