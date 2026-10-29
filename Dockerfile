FROM python:3.12-slim

WORKDIR /code

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

#не от root, data заранее чтоб volume взял владельца
RUN useradd --create-home --uid 1000 app && mkdir -p data && chown -R app /code/data
USER app

CMD ["uvicorn", "sitegen.main:app", "--host", "0.0.0.0", "--port", "8000"]
