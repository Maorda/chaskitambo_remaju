import os
import asyncio
import logging
from pathlib import Path
from dotenv import load_dotenv

# Configuración básica de logging para auditoría del bot
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ==============================================================================
# ESTRATEGIA DE CARGA EXPLÍCITA DEL .ENV DE CHASKITAMBO
# ==============================================================================
# Buscamos el archivo .env directamente en la ruta fija provista: D:\libs\chaskitambo
# Si por alguna razón se mueve, el respaldo buscará en la raíz de ejecución actual.
CHASKITAMBO_ROOT = Path(r"D:\libs\chaskitambo")
DOTENV_PATH = CHASKITAMBO_ROOT / ".env"

if DOTENV_PATH.exists():
    logger.info(f"[ENV] Cargando configuración explícita desde: {DOTENV_PATH}")
    load_dotenv(dotenv_path=DOTENV_PATH, override=False)
else:
    logger.warning(f"[ENV] No se encontró .env en {CHASKITAMBO_ROOT}. Buscando de forma local en el directorio de trabajo...")
    load_dotenv(override=False)


class RemajuAuthError(Exception):
    """Excepción personalizada para errores críticos de autenticación en REMAJU."""
    pass


class RemajuAuthenticator:
    def __init__(self, page, resolver_ia):
        """
        Inicializa el handler de autenticación asíncrono con Playwright.
        Las credenciales se extraen de manera segura a través de variables de entorno (.env).
        :param page: Objeto de página (Page) de Playwright.
        :param resolver_ia: Instancia única del resolvedor de captcha (CaptchaResolver).
        """
        self.page = page
        self.ocr = resolver_ia
        self.max_retries = 5

    def load_credentials(self) -> dict:
        """Carga y valida las credenciales críticas desde el entorno inyectado por el .env."""
        usuario = os.getenv("CHASKITAMBO_REMAJU_USUARIO")
        clave = os.getenv("CHASKITAMBO_REMAJU_CLAVE")
        
        if not usuario or not clave:
            raise RemajuAuthError(
                "Faltan las variables de entorno cruciales. Por favor, asegúrate de definir "
                "CHASKITAMBO_REMAJU_USUARIO y CHASKITAMBO_REMAJU_CLAVE en tu archivo .env"
            )
            
        return {
            "usuario": usuario,
            "clave": clave,
            "url_base": os.getenv("CHASKITAMBO_REMAJU_URL_BASE", "https://pj.gob.pe"),
            "url_login_path": os.getenv("CHASKITAMBO_REMAJU_URL_LOGIN_PATH", "/pages/seguridad/login.xhtml")
        }

    async def execute_login(self) -> bool:
        """Flujo principal asíncrono de autenticación utilizando Playwright."""
        creds = self.load_credentials()
        target_login_url = f"{creds['url_base']}{creds['url_login_path']}"

        logger.info(f"[INFO] 0. Cargando la página: {target_login_url}")
        await self.page.goto(target_login_url)
        await self.page.wait_for_load_state("domcontentloaded")

        logger.info("[INFO] 1. Evaluando modal de bienvenida...")
        try:
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
            logger.info(f"\n--- Intento {intento + 1} de {self.max_retries} ---")
            
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
            
            # Click real sobre el botón de sumisión oficial
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
