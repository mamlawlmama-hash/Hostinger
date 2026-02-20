# Sử dụng Python image chính thức
FROM python:3.9-slim

# Đặt thư mục làm việc trong container
WORKDIR /app

# Copy requirements.txt trước để tận dụng Docker cache
COPY requirements.txt .

# Cài đặt các dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy toàn bộ source code vào container
COPY . .

# Expose port (thay đổi port nếu ứng dụng của bạn dùng port khác)
EXPOSE 8080

# Chạy ứng dụng với host 0.0.0.0 để có thể truy cập từ bên ngoài container
CMD ["python", "app.py"]