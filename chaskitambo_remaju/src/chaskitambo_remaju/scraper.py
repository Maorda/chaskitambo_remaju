# D:\libs\chaskitambo_plugins\chaskitambo_remaju\src\chaskitambo_remaju\scraper.py
import asyncio
import logging
import os
from collections.abc import AsyncGenerator
from pathlib import Path

from chaskitambo import BaseScraper, ChaskiDocument
from playwright.async_api import async_playwright

from .auth import RemajuAuthenticator
from .extractor import RemajuExtractorScraper
from .history import RemajuHistoryManager
from .ocr import CaptchaResolver
from .search import RemajuSearchScraper

logger = logging.getLogger(__name__)
BASE_DIR = Path(__file__).resolve().parent


class RemajuScraper(BaseScraper):

  def __init__(
      self,
      limite_items: int = None,
      history_path: str | Path = None,
      config_path: str | Path = BASE_DIR / "config.json",
      headless: bool = False,
      executable_path: str = r"D:\libs\navegadores\chrome-win64\chrome.exe",
      ejecutar_reintentos: bool = True,
  ):
    self.limite_items = limite_items  # 👈 Captura correcta del límite desde el YAML
    self.history_path = history_path
    self.config_path = Path(config_path)
    self.headless = headless
    self.executable_path = executable_path
    self.ejecutar_reintentos = ejecutar_reintentos

  async def _procesar_tarjeta_actual(
      self,
      page,
      extractor,
      history_manager,
      identificador_tarjeta,
      numero_convocatoria,
      ruta_local_descargas,
  ):
    """Extrae y empaqueta la información de una tarjeta individual."""
    # Cortocircuito Alimentos
    xpath_materia = (
        "//div[contains(@class, 'ui-g')][div[contains(text(),"
        " 'Materia')]]/div[last()]"
    )
    try:
      materia_text = (
          await page.locator(xpath_materia).first.inner_text(timeout=3000)
      ).strip()
      if "alimentos" in " ".join(materia_text.lower().split()):
        logger.info(
            f" -> Tarjeta {identificador_tarjeta} descartada por materia"
            " alimentos."
        )
        return None
    except Exception:
      pass

    # Extracción de la ficha detallada navegando por pestañas
    detalle_extraido = await extractor.extract_tab_remate_completo()

    expediente_real_judicial = (
        detalle_extraido.get("remate", {}).get("expediente", "").strip()
    )
    convocatoria_real_judicial = (
        detalle_extraido.get("remate", {}).get("convocatoria", "").strip()
        or numero_convocatoria
    )

    if not expediente_real_judicial:
      expediente_real_judicial = identificador_tarjeta

    # =========================================================================
    # VALIDACIÓN ESTRICTA POR NÚMERO DE EXPEDIENTE (Evita doble evaluación)
    # =========================================================================
    if history_manager.is_processed(expediente_real_judicial, convocatoria_real_judicial):
      logger.info(
          f" -> [HISTORIAL] Expediente ya procesado anteriormente: {expediente_real_judicial}. Saltando..."
      )
      return None

    # Validación de integridad de datos clave
    tipo_cambio = detalle_extraido.get("remate", {}).get("tipoCambio", "")
    if not tipo_cambio:
      logger.warning(
          f" -> [ALERTA] Tipo de cambio no encontrado para"
          f" {expediente_real_judicial}."
      )

    nombre_pdf = await extractor.download_resolucion_pdf(
        expediente_real_judicial, str(ruta_local_descargas)
    )

    pdf_bytes = b""
    if nombre_pdf:
      ruta_pdf = ruta_local_descargas / nombre_pdf
      if ruta_pdf.is_file():
        pdf_bytes = await asyncio.to_thread(ruta_pdf.read_bytes)

    detalle_extraido["remate"]["expediente"] = expediente_real_judicial
    detalle_extraido["remate"]["convocatoria"] = convocatoria_real_judicial
    dto_mapeado = extractor.adaptar_a_dto(detalle_extraido, nombre_pdf)

    documento = ChaskiDocument(
        id_externo=expediente_real_judicial,
        fuente="remaju",
        metadatos={
            "convocatoria": convocatoria_real_judicial,
            "detalle": dto_mapeado,
        },
        pdf_bytes=pdf_bytes,
        nombre_archivo_sugerido=nombre_pdf
        or f"resolucion_{expediente_real_judicial}.pdf",
    )

    history_manager.save_processed(
        expediente_real_judicial, convocatoria_real_judicial
    )
    return documento

  async def extract(self) -> AsyncGenerator[ChaskiDocument, None]:
    logger.info(" -> [REMAJU-PLUGIN] Iniciando ejecución autónoma...")
    emitidos_count = 0  # 👈 Contador para controlar el límite de ítems

    history_manager = RemajuHistoryManager(self.history_path)
    captcha_builder = CaptchaResolver()
    tipo_inmueble_filtro = "1"
    ruta_local_descargas = Path("./descargas_resoluciones")
    ruta_local_descargas.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as p:
      launch_kwargs = {"headless": self.headless}
      if os.path.isfile(self.executable_path):
        launch_kwargs["executable_path"] = self.executable_path

      browser = await p.chromium.launch(**launch_kwargs)
      context = await browser.new_context(
          viewport={"width": 1280, "height": 720}, accept_downloads=True
      )
      page = await context.new_page()

      try:
        authenticator = RemajuAuthenticator(page, captcha_builder)
        if not await authenticator.execute_login():
          return

        search_scraper = RemajuSearchScraper(
            page, history_manager=history_manager
        )
        await search_scraper.navigate_to_search_module()

        extractor = RemajuExtractorScraper(
            page, config_path=self.config_path
        )

        # =====================================================================
        # FASE 1: BARRIDO MASIVO GENERAL DE LA PLATAFORMA
        # =====================================================================
        logger.info(" -> [FASE 1] Iniciando barrido masivo general...")
        await search_scraper.apply_search_filters(tipo_inmueble_filtro)
        pagina_num = 1
        detener_extraccion = False

        while True and not detener_extraccion:
          logger.info(
              " -> [REMAJU-PLUGIN] Procesando página #%s...", pagina_num
          )
          await extractor.esperar_sincronizacion_primefaces()
          await page.wait_for_selector(
              "div.card.azul", state="visible", timeout=15000
          )

          tarjetas_procesadas_en_pagina = 0
          while True and not detener_extraccion:
            await extractor.esperar_sincronizacion_primefaces()
            await page.wait_for_selector(
                "div.card.azul", state="visible", timeout=15000
            )

            num_tarjetas = await page.locator("div.card.azul").count()
            if tarjetas_procesadas_en_pagina >= num_tarjetas:
              break

            tarjeta_actual = page.locator("div.card.azul").nth(
                tarjetas_procesadas_en_pagina
            )
            btn_detalle = tarjeta_actual.locator(
                "button:has-text('Detail'), button:has-text('Detalle')"
            ).first

            if await btn_detalle.count() == 0:
              tarjetas_procesadas_en_pagina += 1
              continue

            raw_title = (
                await tarjeta_actual.locator(".label-danger, .h6")
                .first.inner_text()
            ).strip()
            if "REMATE N°" not in raw_title or " - " not in raw_title:
              tarjetas_procesadas_en_pagina += 1
              continue

            parts = raw_title.split(" - ", 1)
            identificador_tarjeta, numero_convocatoria = (
                parts[0].strip(),
                parts[1].strip(),
            )

            en_detalle = False
            try:
              await btn_detalle.click(force=True)
              await page.wait_for_selector(
                  "button:has-text('Regresar'), a:has-text('Regresar')",
                  state="visible",
                  timeout=15000,
              )
              await extractor.esperar_sincronizacion_primefaces()
              en_detalle = True

              doc = await self._procesar_tarjeta_actual(
                  page,
                  extractor,
                  history_manager,
                  identificador_tarjeta,
                  numero_convocatoria,
                  ruta_local_descargas,
              )
              emitidos_count += 1
              if doc:
                yield doc
                
                logger.info(f" -> [REMAJU-PLUGIN] Ítem válido emitido ({emitidos_count}/{self.limite_items or 'Sin límite'})")

                # 🛑 COMPROBACIÓN DE LÍMITE DE PRUEBA CONFIGURADO EN EL YAML
              if self.limite_items and emitidos_count >= self.limite_items:
                logger.info(f" -> [REMAJU-PLUGIN] Límite de ítems ({self.limite_items}) alcanzado. Deteniendo extracción.")
                detener_extraccion = True
                break

              tarjetas_procesadas_en_pagina += 1

            except Exception as e:
              logger.exception(
                  f" -> Error procesando tarjeta {identificador_tarjeta}"
              )
              history_manager.save_failed(
                  identificador_tarjeta,
                  numero_convocatoria,
                  motivo=str(e),
              )
              tarjetas_procesadas_en_pagina += 1
            finally:
              if en_detalle:
                try:
                  btn_regresar = page.locator(
                      "button:has-text('Regresar'),"
                      " a:has-text('Regresar')"
                  ).first
                  await btn_regresar.click(force=True)
                  await page.wait_for_selector(
                      "div.card.azul", state="visible", timeout=15000
                  )
                  await extractor.esperar_sincronizacion_primefaces()
                except Exception:
                  logger.exception(
                      " -> Error retornando a la bandeja general."
                  )

          if detener_extraccion:
            break

          btn_siguiente = page.locator(
              "a.ui-paginator-next:not(.ui-state-disabled)"
          ).first
          if (
              await btn_siguiente.count() == 0
              or not await btn_siguiente.is_visible()
          ):
            break

          pagina_num += 1
          await btn_siguiente.click(force=True)
          await extractor.esperar_sincronizacion_primefaces()

        # =====================================================================
        # FASE 2: PROCESAMIENTO DE LA COLA DE REINTENTOS CON FILTRO ESPECÍFICO
        # =====================================================================
        if self.ejecutar_reintentos and not (self.limite_items and emitidos_count >= self.limite_items):
          items_fallidos = history_manager.get_failed_items()
          if items_fallidos:
            logger.info(
                f"\n -> [FASE 2] Iniciando reintentos para"
                f" {len(items_fallidos)} remates fallidos..."
            )

            for item in items_fallidos:
              if self.limite_items and emitidos_count >= self.limite_items:
                break

              remate_id = item.get("remate")
              convocatoria_id = item.get("convocatoria", "")
              logger.info(
                  f" -> [REINTENTO] Buscando remate con filtro: {remate_id}"
              )

              try:
                await search_scraper.search_by_remate_number(remate_id)
                await extractor.esperar_sincronizacion_primefaces()

                if await page.locator("div.card.azul").count() == 0:
                  logger.warning(
                      f" -> [REINTENTO] No se encontraron resultados para"
                      f" {remate_id}"
                  )
                  continue

                tarjeta_actual = page.locator("div.card.azul").first
                btn_detalle = tarjeta_actual.locator(
                    "button:has-text('Detail'), button:has-text('Detalle')"
                ).first

                if await btn_detalle.count() == 0:
                  continue

                await btn_detalle.click(force=True)
                await page.wait_for_selector(
                    "button:has-text('Regresar'), a:has-text('Regresar')",
                    state="visible",
                    timeout=15000,
                )
                await extractor.esperar_sincronizacion_primefaces()

                doc = await self._procesar_tarjeta_actual(
                    page,
                    extractor,
                    history_manager,
                    remate_id,
                    convocatoria_id,
                    ruta_local_descargas,
                )
                if doc:
                  yield doc
                  emitidos_count += 1

              except Exception as e:
                logger.error(
                    f" -> [REINTENTO FALLIDO] Fallo al reintentar {remate_id}:"
                    f" {e}"
                )
              finally:
                try:
                  btn_regresar = page.locator(
                      "button:has-text('Regresar'),"
                      " a:has-text('Regresar')"
                  ).first
                  if (
                      await btn_regresar.count() > 0
                      and await btn_regresar.is_visible()
                  ):
                    await btn_regresar.click(force=True)
                    await page.wait_for_selector(
                        "div.card.azul", state="visible", timeout=15000
                    )
                    await extractor.esperar_sincronizacion_primefaces()
                except Exception:
                  pass

      finally:
        logger.info(
            " -> [REMAJU-PLUGIN] Liberando controladores de Playwright..."
        )
        await page.close()
        await context.close()
        await browser.close()