FROM python:3.10

RUN useradd -m -u 1000 user && python -m pip install --upgrade pip
USER user
ENV PATH="/home/user/.local/bin:$PATH"

WORKDIR /app

COPY ./mcp_output/requirements.txt requirements.txt
RUN pip install --no-cache-dir --upgrade -r requirements.txt \
    && pip install --no-cache-dir obspy

COPY . /app

ENV MCP_TRANSPORT=http
ENV MCP_PORT=7860

EXPOSE 7860

CMD ["python", "mcp_output/start_mcp.py"]
