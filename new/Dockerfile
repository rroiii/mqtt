# Gunakan base image Python
FROM python:3.10

# Set working directory
WORKDIR /app

# Salin file requirements.txt ke dalam container
COPY requirements.txt .

# Install dependensi Python
RUN pip install --no-cache-dir -r requirements.txt

# Salin seluruh proyek ke dalam container
COPY . .

# Expose port aplikasi
EXPOSE 8000

# Perintah untuk menjalankan aplikasi
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]