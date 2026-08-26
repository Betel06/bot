"""
HUNTERA LOGIN - Execute uma vez no PC
Abre navegador visível, você loga com Google, e salva a sessão pro bot usar.
"""
import os
import json
from playwright.sync_api import sync_playwright

SESSION_FILE = os.path.join(os.path.dirname(__file__), "huntera_session.json")
GAME_URL = "https://huntera.com.br/game"

def main():
    print("=" * 50)
    print("HUNTERA LOGIN - Primeira vez")
    print("=" * 50)
    print()
    print("1. Vou abrir o navegador no Huntera")
    print("2. Clique em 'Logar com email' (Google)")
    print("3. Escolha sua conta Google")
    print("4. Quando estiver LOGADO no jogo, volte aqui e aperte ENTER")
    print()

    with sync_playwright() as p:
        # Abre navegador visível (não headless)
        browser = p.chromium.launch(headless=False, args=[
            "--disable-blink-features=AutomationControlled"
        ])
        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        # Navega pro jogo
        print("[1/4] Abrindo Huntera...")
        page.goto(GAME_URL, wait_until="networkidle", timeout=30000)
        print(f"  URL: {page.url}")
        print(f"  Titulo: {page.title()}")

        print()
        print(">>> FAÇA O LOGIN COM GOOGLE AGORA <<<")
        print(">>> Quando estiver dentro do jogo, aperte ENTER aqui <<<")
        print()

        input("Pressione ENTER quando estiver logado no jogo...")

        # Verifica se logou
        current_url = page.url
        print(f"[2/4] URL atual: {current_url}")

        # Tenta pegar dados da sessão
        print("[3/4] Salvando sessão...")

        # Salva storage state (cookies + localStorage)
        storage = context.storage_state()

        # Salva em arquivo
        with open(SESSION_FILE, "w", encoding="utf-8") as f:
            json.dump(storage, f, indent=2, ensure_ascii=False)

        file_size = os.path.getsize(SESSION_FILE)
        print(f"  Sessão salva: {SESSION_FILE}")
        print(f"  Tamanho: {file_size} bytes")
        print(f"  Cookies: {len(storage.get('cookies', []))}")

        # Salva também uma screenshot do estado atual
        screenshot_path = os.path.join(os.path.dirname(__file__), "huntera_logado.png")
        page.screenshot(path=screenshot_path)
        print(f"  Screenshot: {screenshot_path}")

        # Pega informações do jogo (se disponível)
        print("[4/4] Extraindo info do jogo...")
        try:
            game_info = page.evaluate("""() => {
                const info = {};
                // Tenta pegar dados do localStorage
                for (let i = 0; i < localStorage.length; i++) {
                    const key = localStorage.key(i);
                    info[key] = localStorage.getItem(key);
                }
                return info;
            }""")
            print(f"  localStorage keys: {list(game_info.keys())[:10]}")

            # Salva localStorage separadamente
            local_storage_path = os.path.join(os.path.dirname(__file__), "huntera_localstorage.json")
            with open(local_storage_path, "w", encoding="utf-8") as f:
                json.dump(game_info, f, indent=2, ensure_ascii=False)
            print(f"  localStorage salvo: {local_storage_path}")
        except Exception as e:
            print(f"  Aviso: não conseguiu extrair localStorage: {e}")

        browser.close()

    print()
    print("=" * 50)
    print("LOGIN CONCLUIDO!")
    print(f"Sessão salva em: {SESSION_FILE}")
    print()
    print("Agora o bot pode usar essa sessão pra ficar logado 24/7.")
    print("Se a sessão expirar, execute este script de novo.")
    print("=" * 50)


if __name__ == "__main__":
    main()
