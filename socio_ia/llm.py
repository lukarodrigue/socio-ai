"""Cliente de modelo local (Ollama). Opcional no Beta.

Regra de projeto: a IA só escreve texto. Números, valores e decisões nunca vêm dela.
Se o modelo estiver fora do ar, lento ou responder errado, o sistema segue sem ele.
"""
import httpx


def gerar_texto(url: str, modelo: str, prompt: str, timeout: float = 60.0) -> str | None:
    if not url:
        return None
    try:
        r = httpx.post(f"{url.rstrip('/')}/api/generate",
                       json={"model": modelo, "prompt": prompt, "stream": False, "options": {"temperature": 0.3}},
                       timeout=timeout)
        r.raise_for_status()
        texto = (r.json().get("response") or "").strip()
        return texto or None
    except (httpx.HTTPError, ValueError):
        return None
