import asyncio
import os
import json
import logging
from pathlib import Path
from playwright.async_api import async_playwright

from chaskitambo import BaseScraper, ChaskiDocument

# Importación de los submódulos internos adaptados del scraper REMAJU
from .auth import RemajuAuthenticator
from .history import RemajuHistoryManager
from .search import RemajuSearchScraper
from .extractor import RemajuExtractorScraper
from .ocr import CaptchaResolver

logger = logging.getLogger(__name__)

class RemajuScraper(BaseScraper):
    """
    Plugin autónomo de REMAJU para Chaskitambo.
    Encapsula navegación, login, resolución de captcha por IA, extracción 
    por pestañas y emisión de ChaskiDocument con bytes de PDF.
    """

    def __init__(self, creds_path: str = "autenticacion.json", history_path: str = "historial_procesados.json", config_path: str = "config.json"):
        self.creds_path = creds_path
        self.history_path = history_path
        self.config_path = config_path

    async def extract(self) -> AsyncGenerator[ChaskiDocument, None]:
        logger.info(" -> [REMAJU-PLUGIN] Iniciando ejecución autónoma del scraper REMAJU...")
        
        # 1. Inicializar componentes auxiliares
        history_manager = RemajuHistoryManager(self.history_path)
        captcha_builder = CaptchaResolver()
        tipo_inmueble_filtro = "1"
        ruta_local_descargas = './descargas_resoluciones'
        
        # 2. Lanzar Playwright de forma autónoma
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=False) # Puede configurarse a True
            context = await browser.new_context(
                viewport={"width": 1280, "height": 720},
                accept_downloads=True
            )
            page = await context.new_page()
            
            try:
                # 3. Autenticación
                authenticator = RemajuAuthenticator(page, captcha_builder, creds_path=self.creds_path)
                login_success = await authenticator.execute_login()
                if not login_success:
                    logger.error(" -> [REMAJU-PLUGIN] Falló la autenticación. Abortando plugin.")
                    await browser.close()
                    return
                
                # 4. Búsqueda perimetral
                search_scraper = RemajuSearchScraper(page, history_manager=history_manager)
                await search_scraper.navigate_to_search_module()
                await search_scraper.apply_search_filters(tipo_inmueble_filtro)
                
                # 5. Extractor por pestañas
                extractor = RemajuExtractorScraper(page, config_path=self.config_path)
                pagina_num = 1
                
                while True:
                    logger.info(f" -> [REMAJU-PLUGIN] Procesando página #{pagina_num}...")
                    await extractor.esperar_sincronizacion_primefaces()
                    await page.wait_for_selector("div.card.azul", state="visible", timeout=15000)
                    
                    remates_pagina = await page.evaluate('''
                        () => {
                            const resultados = [];
                            document.querySelectorAll('div.card.azul').forEach(card => {
                                const header = card.querySelector('.label-danger, .h6')?.innerText.trim() || '';
                                if (header) { resultados.push({ titulo_tarjeta: header }); }
                            });
                            return resultados;
                        }
                    ''')
                    
                    num_tarjetas = len(remates_pagina)
                    
                    for i in range(num_tarjetas):
                        await extractor.esperar_sincronizacion_primefaces()
                        await page.wait_for_selector("div.card.azul", state="visible", timeout=15000)
                        
                        tarjeta_actual = page.locator("div.card.azul").nth(i)
                        btn_detalle = tarjeta_actual.locator("button:has-text('Detalle')").first
                        
                        if await btn_detalle.count() > 0:
                            raw_title = await tarjeta_actual.locator(".label-danger, .h6").first.inner_text()
                            if "REMATE N°" in raw_title and " - " in raw_title:
                                parts = raw_title.split(" - ")
                                numero_expediente = parts[0].strip()
                                numero_convocatoria = parts[1].strip()
                            else:
                                numero_expediente = f"EXP-FALLBACK-{i+1}"
                                numero_convocatoria = "PRIMERA CONVOCATORIA"
                                
                            # Validación de Historial
                            if history_manager.is_processed(numero_expediente, numero_convocatoria):
                                continue
                                
                            # Entrar al detalle
                            try:
                                await btn_detalle.click(force=True)
                                await page.wait_for_selector("button:has-text('Regresar'), a:has-text('Regresar')", state="visible", timeout=15000)
                                await extractor.esperar_sincronizacion_primefaces()
                            except Exception as e:
                                continue
                                
                            btn_regresar = page.locator("button:has-text('Regresar'), a:has-text('Regresar')").first
                            
                            # Cortocircuito de Alimentos
                            xpath_materia = "//div[contains(@class, 'ui-g')][div[contains(text(), 'Materia')]]/div[contains(@class, 'text-justify') or contains(@class, 'ui-panelgrid-cell')][last()]"
                            try:
                                materia_text = (await page.locator(xpath_materia).first.inner_text(timeout=3000)).strip()
                            except:
                                materia_text = ""
                                
                            if materia_text == "Pago por alimentos":
                                await btn_regresar.click(force=True)
                                await page.wait_for_selector("div.card.azul", state="visible", timeout=15000)
                                continue
                            
                            # Extraer datos de pestañas
                            try:
                                detalle_extraido = await extractor.extract_tab_remate_completo()
                            except Exception:
                                detalle_extraido = {"remate": {"expediente": numero_expediente}}
                                
                            # Descarga de PDF y lectura de bytes crudos
                            nombre_pdf_descargado = await extractor.download_resolucion_pdf(numero_expediente, ruta_local_descargas)
                            pdf_bytes = b""
                            if nombre_pdf_descargado:
                                ruta_pdf_completa = os.path.join(ruta_local_descargas, nombre_pdf_descargado)
                                if os.path.exists(ruta_pdf_completa):
                                    with open(ruta_pdf_completa, "rb") as f:
                                        pdf_bytes = f.read()

                            # Adaptación a DTO limpio
                            dto_mapeado = extractor.adaptar_a_dto(detalle_extraido, nombre_pdf_descargado)
                            
                            # Registrar en historial local
                            history_manager.save_processed(numero_expediente, numero_convocatoria)
                            
                            # Emitir el ChaskiDocument hacia el motor Chaskitambo
                            yield ChaskiDocument(
                                id_externo=numero_expediente,
                                fuente="remaju",
                                metadatos={
                                    "convocatoria": numero_convocatoria,
                                    "detalle": dto_mapeado
                                },
                                pdf_bytes=pdf_bytes,
                                nombre_archivo_sugerido=nombre_pdf_descargado or f"resolucion_{numero_expediente}.pdf"
                            )
                            
                            # Retornar a la bandeja general
                            try:
                                await btn_regresar.click(force=True)
                                await page.wait_for_selector("div.card.azul", state="visible", timeout=15000)
                            except Exception:
                                pass
                                
                            await extractor.esperar_sincronizacion_primefaces()
                            
                    # Paginación
                    btn_siguiente = page.locator("a.ui-paginator-next:not(.ui-state-disabled)").first
                    if await btn_siguiente.is_visible():
                        pagina_num += 1
                        await btn_siguiente.click(force=True)
                        await extractor.esperar_sincronizacion_primefaces()
                    else:
                        break
                        
                await browser.close()
            except Exception as e:
                logger.error(f" -> [ERROR] Falló la ejecución del plugin REMAJU: {e}")
                try:
                    await browser.close()
                except Exception:
                    pass