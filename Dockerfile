# Start with a Python 3.11 base image (lightweight version)
FROM python:3.11-slim

# Set the working directory inside the container
WORKDIR /app

# Copy your requirements.txt file first
COPY requirements.txt .

# Install all Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy all your project files into the container
COPY . .

# Tell Docker your app uses port 8080
EXPOSE 8080

# Command to run when container starts
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "main:app"]
```

### **Step 3: Make Sure Gunicorn is in requirements.txt**

Open `requirements.txt` and ensure this line is there:
```
gunicorn
```

If it's not there, add it.

### **Step 4: Create a .dockerignore File** (Optional but recommended)

Create `.dockerignore` in your project root to exclude unnecessary files:
```
__pycache__
*.pyc
*.pyo
*.pyd
.Python
venv/
env/
.env
.git
.vscode
*.db
node_modules