FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8080

CMD ["gunicorn", "--bind", "0.0.0.0:8080", "main:app"]
```

## **Common Mistakes to Check:**

1. **Remove any ``` marks** at the top or bottom
2. **No quotes around the whole file**
3. **No extra spaces or special characters**
4. **File should be named exactly `Dockerfile`** (capital D, no extension)

## **How to Fix It:**

1. Open your `Dockerfile` in VS Code
2. Delete everything
3. Copy and paste this clean version:
```
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8080

CMD ["gunicorn", "--bind", "0.0.0.0:8080", "main:app"]