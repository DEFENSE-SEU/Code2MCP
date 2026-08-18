FROM python:3.11
RUN useradd -m -u 1000 user && \
    python -m pip install --upgrade pip
USER user
ENV PATH="/home/user/.local/bin:$PATH"
WORKDIR /app

COPY --chown=user ./requirements.txt requirements.txt
RUN pip install --no-cache-dir --upgrade -r requirements.txt

COPY --chown=user . /app
ENV PYTHONPATH=/app/esm/source:$PYTHONPATH
EXPOSE 7860
ENV MCP_TRANSPORT=http
ENV MCP_PORT=7860
CMD ["python", "esm/mcp_output/start_mcp.py"]