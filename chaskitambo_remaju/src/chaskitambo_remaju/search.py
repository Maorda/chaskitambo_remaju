import asyncio
import logging

logger = logging.getLogger(__name__)

class RemajuSearchScraper:
    def __init__(self, page, history_manager=None):
        """
        Inicializa el módulo de búsqueda perimetral adaptado a Playwright.
        :param page: Objeto de página (Page) de Playwright.
        :param history_manager: Instancia del gestor histórico local (HistoryManager).
        """
        self.page = page
        self.history_manager = history_manager

    async def navigate_to_search_module(self) -> bool:
        """Navega de forma robusta por el acordeón de menús hasta el recurso de búsqueda."""
        logger.info("[INFO] 7. Navegando a 'BUSCAR REMATES'...")
        
        # Localizar el contenedor del menú usando el selector institucional verificado
        menu_padre = self.page.locator("li[id='linkRemateJudicial']")
        submenu_buscar = self.page.locator("li[id='linkBuscarRematesPublicados']")
        
        if not await submenu_buscar.is_visible():
            await menu_padre.click()
            await self.page.wait_for_timeout(1000)

        await self.page.click("li[id='linkBuscarRematesPublicados'] a")
        await self.page.wait_for_load_state("domcontentloaded")
        return True

    async def apply_search_filters(self, tipo_inm: str):
        """Abre la bandeja de resultados y ejecuta la búsqueda masiva total sin restricciones."""
        # =========================================================================================
        # SE COMENTÓ EL ACCESO AL ACORDEÓN POR TIPO DE INMUEBLE PARA PROCESAR LA GRILLA MASIVA TOTAL
        # =========================================================================================
        # logger.info(f"[INFO] 8. Aplicando filtro de Inmueble (Código: {tipo_inm})...")
        # accordion_header = self.page.locator("[id*='filtroTipoInmueble'], [id*='j_idt165_header']").first
        # if await accordion_header.count() > 0 and await accordion_header.get_attribute("aria-expanded") == "false":
        #     await accordion_header.click()
        #     await self.page.wait_for_timeout(500)
        # await self.page.select_option("select[id*='filtroTipoInmueble_input']", value=str(tipo_inm), force=True)
        # await self.page.wait_for_timeout(500)
        # =========================================================================================

        # Gatillar búsqueda masiva total directa hacia el servidor de PrimeFaces
        logger.info("[INFO] 8. Gatillando búsqueda masiva total sin restricciones de propiedad...")
        btn_buscar = self.page.locator("button:has-text('Buscar'), button[id*='j_idt177']").first
        await btn_buscar.click()
