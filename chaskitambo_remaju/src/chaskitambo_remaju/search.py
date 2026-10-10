# D:\libs\chaskitambo_plugins\chaskitambo_remaju\src\chaskitambo_remaju\search.py
import logging

logger = logging.getLogger(__name__)


class RemajuSearchScraper:

  def __init__(self, page, history_manager=None):
    """Inicializa el módulo de búsqueda perimetral adaptado a Playwright[cite: 6].

    :param page: Objeto de página (Page) de Playwright[cite: 6].
    :param history_manager: Instancia del gestor histórico local
    (HistoryManager)[cite: 6].
    """
    self.page = page
    self.history_manager = history_manager

  async def navigate_to_search_module(self) -> bool:
    """Navega de forma robusta por el acordeón de menús hasta el recurso de búsqueda[cite: 6]."""
    logger.info("[INFO] Navegando a 'BUSCAR REMATES'...")

    menu_padre = self.page.locator("li[id='linkRemateJudicial']")
    submenu_buscar = self.page.locator(
        "li[id='linkBuscarRematesPublicados']"
    )

    if not await submenu_buscar.is_visible():
      await menu_padre.click()
      await self.page.wait_for_timeout(1000)

    await self.page.click("li[id='linkBuscarRematesPublicados'] a")
    await self.page.wait_for_load_state("domcontentloaded")
    return True

  async def apply_search_filters(self, tipo_inm: str = None):
    """Gatilla la búsqueda masiva total sin restricciones[cite: 6]."""
    logger.info(
        "[INFO] Gatillando búsqueda masiva total sin restricciones de"
        " propiedad..."
    )
    btn_buscar = self.page.locator(
        "button:has-text('Buscar'), button[id*='j_idt177']"
    ).first
    await btn_buscar.click()

  async def search_by_remate_number(self, numero_remate: str):
    """Ejecuta la búsqueda individualizada utilizando el filtro por 'Número de remate'.

    Aprovecha los selectores oficiales inyectados en la vista PrimeFaces[cite: 5, 6].
    """
    logger.info(
        f"[INFO] Aplicando filtro de búsqueda para Número de Remate:"
        f" {numero_remate}"
    )

    # 1. Asegurar despliegue del panel de acordeón de Filtros
    accordion_header = self.page.locator(
        "a:has-text('Número de remate'),"
        " div[id*='filtroRemate']:has-text('Número de remate')"
    ).first
    try:
      if await accordion_header.count() > 0 and await accordion_header.is_visible():
        await accordion_header.click()
        await self.page.wait_for_timeout(300)
    except Exception:
      pass

    # 2. Inyectar el número de remate en el campo con id 'formBuscarRematesPublicados:j_idt149:filtroRemate'
    selector_input = "input[id='formBuscarRematesPublicados:j_idt149:filtroRemate'], input[id*='filtroRemate']"
    input_field = self.page.locator(selector_input).first
    await input_field.wait_for(state="visible", timeout=5000)
    await input_field.fill("")
    await input_field.fill(str(numero_remate).strip())
    await input_field.press("Tab")

    await self.page.wait_for_timeout(400)

    # 3. Clic en el botón oficial 'APLICAR' con id 'formBuscarRematesPublicados:j_idt177'
    selector_btn_aplicar = "button[id='formBuscarRematesPublicados:j_idt177'], button.btn-rojo:has-text('APLICAR')"
    btn_aplicar = self.page.locator(selector_btn_aplicar).first
    await btn_aplicar.click()

    logger.info(
        f"[OK] Búsqueda por filtro ejecutada para el remate: {numero_remate}"
    )