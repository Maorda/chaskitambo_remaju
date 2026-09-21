import asyncio
import json
import logging
from pathlib import Path

# Configuración básica de logging para auditoría del bot
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class RemajuAuthError(Exception):
    """Excepción personalizada para errores críticos de autenticación en REMAJU."""
    pass

class RemajuAuthenticator:
    def __init__(self, page, resolver_ia, creds_path: str = "autenticacion.json"):
        """
        Inicializa el handler de autenticación asíncrono con Playwright.
        :param page: Objeto de página (Page) de Playwright.
        :param resolver_ia: Instancia única del resolvedor de captcha (CaptchaResolver).
        :param creds_path: Ruta al archivo JSON de credenciales local.
        """
        self.page = page
        self.ocr = resolver_ia
        self.creds_path = Path(creds_path)
        self.max_retries = 5

    def load_credentials(self) -> dict:
        """Carga y valida el archivo de credenciales local verificando el contrato fragmentado."""
        if not self.creds_path.exists():
            logger.error(f"Archivo no encontrado: {self.creds_path}")
            raise FileNotFoundError(f"Archivo de credenciales no encontrado: {self.creds_path}")
        
        with open(self.creds_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            required_keys = ["usuario", "clave", "url_base", "url_login_path"]
            if not all(k in data for k in required_keys):
                raise ValueError(f"El JSON debe contener las claves exactas: {required_keys}")
            return data

    async def execute_login(self) -> bool:
        """Flujo principal asíncrono de autenticación importado del script de Colab."""
        creds = self.load_credentials()
        target_login_url = f"{creds['url_base']}{creds['url_login_path']}"

        logger.info(f"[INFO] 0. Cargando la página: {target_login_url}")
        await self.page.goto(target_login_url)
        await self.page.wait_for_load_state("domcontentloaded")

        logger.info("[INFO] 1. Evaluando modal de bienvenida...")
        try:
            # Usar los selectores exactos verificados del script de Colab
            await self.page.wait_for_selector("button[id='btnAceptarPopup']", state="visible", timeout=4000)
            await self.page.click("button[id='btnAceptarPopup']")
            await self.page.wait_for_selector("div[id='dlgPopUp']", state="hidden", timeout=4000)
            logger.info("[OK] Modal cerrado.")
        except Exception:
            logger.info("No se detectó el popup de bienvenida en el DOM actual. Continuando...")

        logger.info("[INFO] 2. Seleccionando 'Con Casilla'...")
        await self.page.click("span:has-text('Con Casilla')")
        await self.page.wait_for_timeout(1000)

        logger.info("[INFO] 3. Iniciando proceso de Login y Captcha (Max 5 intentos)...")
        login_exitoso = False

        for intento in range(self.max_retries):
            logger.info(f"\n--- Intento {intento + 1} de 5 ---")
            
            # Inyección de Usuario + Simulación de Hardware de tecla Tab
            await self.page.locator("[id='frmLogin:usuario']").fill(creds["usuario"])
            await self.page.locator("[id='frmLogin:usuario']").press("Tab")
            
            # Inyección de Contraseña + Simulación de Hardware de tecla Tab
            await self.page.locator("[id='frmLogin:claveConCasilla']").fill(creds["clave"])
            await self.page.locator("[id='frmLogin:claveConCasilla']").press("Tab")

            # Localizar el elemento del captcha oficial
            selector_imagen = "img[id='frmLogin:imgCaptcha']"
            await self.page.wait_for_selector(selector_imagen, timeout=6000)
            elemento_imagen = self.page.locator(selector_imagen).first

            # Captura de screenshot en memoria y resolución offline con la IA local
            image_bytes = await elemento_imagen.screenshot()
            texto_limpio = self.ocr.resolver_bytes(image_bytes)
            logger.info(f"[OK] Captcha descifrado (IA): '{texto_limpio}'")

            # Inyección de texto de Captcha + Simulación de Hardware de tecla Tab
            await self.page.locator("[id='frmLogin:captcha']").fill(texto_limpio)
            await self.page.locator("[id='frmLogin:captcha']").press("Tab")
            
            # Click real sobre el botón de sumisión oficial de Colab
            await self.page.click("button[id='frmLogin:btnLogin']")

            # Carrera asíncrona concurrente de Playwright para interceptar redirección o alerta Growl
            task_url = asyncio.create_task(self.page.wait_for_url("**/inicio.xhtml", timeout=5000))
            task_growl = asyncio.create_task(self.page.wait_for_selector("div.ui-growl-item", state="visible", timeout=5000))

            done, pending = await asyncio.wait([task_url, task_growl], return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()

            if task_url in done and not task_url.exception():
                logger.info("[OK] Login exitoso.")
                login_exitoso = True
                break
            elif task_growl in done and not task_growl.exception():
                mensaje_web = await self.page.locator("div.ui-growl-item p").first.inner_text()
                logger.warning(f"[WARNING] Error en login: {mensaje_web}")
                # Estabilización de red antes de comenzar la nueva vuelta parcial de AJAX
                await self.page.wait_for_timeout(2000)

        if not login_exitoso:
            logger.error("[ERROR] Se agotaron los intentos de Login. Abortando.")
            return False
            
        return True