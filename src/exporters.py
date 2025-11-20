import re
import html
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, List

def export_to_markdown(content: str, output_path: Optional[Path] = None) -> Path:
    if output_path is None:
        output_dir = Path("output")
        output_dir.mkdir(exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = output_dir / f"analysis-{timestamp}.md"
    
    output_path.write_text(content, encoding="utf-8")
    return output_path

def parse_markdown_sections(content: str) -> Dict[str, str]:
    """
    Estrategia de parsing robusta: Divide el documento por encabezados de nivel 1 (#)
    y asigna secciones buscando palabras clave en el título, sin importar emojis o formato.
    """
    sections = {
        'resumen': '',
        'analisis': '',
        'recomendaciones': '',
        'raw': content
    }
    
    # Normalizar saltos de línea
    content = content.replace('\r\n', '\n')
    
    # Dividir por encabezados de Nivel 1 (# Título)
    # La regex busca el inicio de línea, un #, espacio y el resto.
    chunks = re.split(r'(?m)^#\s+(.*?)\n', content)
    
    # chunks[0] es texto antes del primer header (vacío usualmente)
    # chunks[1] es el título 1, chunks[2] es el contenido 1, chunks[3] título 2...
    for i in range(1, len(chunks), 2):
        title = chunks[i].lower()
        body = chunks[i+1].strip()
        
        if 'resumen' in title:
            sections['resumen'] = body
        elif 'análisis' in title or 'analisis' in title or 'fallos' in title:
            sections['analisis'] = body
        elif 'recomendaciones' in title:
            sections['recomendaciones'] = body
            
    return sections

def extract_failure_categories(analisis_text: str) -> List[Dict[str, str]]:
    categories = []
    if not analisis_text:
        return categories

    # Dividir por encabezados de nivel 2 (##) independientemente de lo que siga (emojis, texto)
    raw_blocks = re.split(r'(?m)^##\s+', analisis_text)
    
    for block in raw_blocks:
        if not block.strip():
            continue
            
        lines = block.strip().split('\n')
        # Limpiar el título de emojis y markdown extra para visualización limpia
        raw_title = lines[0].strip()
        # Elimina caracteres markdown de cierre si existen y emojis básicos del inicio
        title = raw_title
        
        # Extracción de campos usando regex flexible que salta emojis y **
        # Busca: **Gravedad:** Alta  O  Gravedad: Alta
        gravedad_match = re.search(r'(?:\*\*|)?Gravedad:?(?:\*\*|)?\s*(.+)', block, re.IGNORECASE)
        gravedad = gravedad_match.group(1).strip() if gravedad_match else "No especificada"
        
        cantidad_match = re.search(r'(?:\*\*|)?Cantidad:?(?:\*\*|)?\s*(.+)', block, re.IGNORECASE)
        cantidad = cantidad_match.group(1).strip() if cantidad_match else ""
        
        # Causa: Busca desde la etiqueta hasta el siguiente doble salto o etiqueta fuerte
        causa_match = re.search(r'(?:\*\*|)?Causa( probable)?:?(?:\*\*|)?\s*\n(.*?)(?=\n\*\*|\n#|$)', block, re.DOTALL | re.IGNORECASE)
        causa = causa_match.group(2).strip() if causa_match else ""
        
        # Tests afectados: Busca lista de viñetas
        tests = []
        tests_section = re.search(r'(?:\*\*|)?Tests( afectados)?:?(?:\*\*|)?\s*\n(.*?)(?=\n\*\*|\n#|$)', block, re.DOTALL | re.IGNORECASE)
        if tests_section:
            test_lines = tests_section.group(2).strip().split('\n')
            for line in test_lines:
                # Captura líneas que empiezan por -, *, o 1.
                clean = re.sub(r'^[\-\*\d\.]+\s+', '', line.strip())
                if clean and len(clean) > 3: # Filtro de ruido
                    tests.append(clean)
        
        categories.append({
            'title': html.escape(title),
            'gravedad': html.escape(gravedad),
            'cantidad': html.escape(cantidad),
            'causa': html.escape(causa).replace('\n', '<br>'),
            'tests': [html.escape(t) for t in tests],
            'raw': block
        })
    
    return categories

def extract_recommendations(text: str) -> Dict[str, List[str]]:
    recs = {'critico': [], 'importante': [], 'menor': []}
    if not text:
        return recs

    # Estrategia: Buscar bloques que empiecen por **[Emoji] Texto:**
    
    # Regex genérica para capturar listas de items
    # Busca cualquier línea que empiece con guión o asterisco
    def parse_list(content):
        items = []
        for line in content.split('\n'):
            clean = line.strip()
            if clean.startswith('- ') or clean.startswith('* '):
                items.append(html.escape(clean[2:]))
        return items

    # Dividir el texto por los encabezados de prioridad (identificados por negrita **)
    # Ejemplo input: **🔴 Crítico:** ...items... **🟡 Importante:** ...
    
    # Crítico
    critico_block = re.search(r'\*\*.*?(?:Cr[ií]tico|Inmediat).*?\*\*(.*?)(?=\*\*|$)', text, re.DOTALL | re.IGNORECASE)
    if critico_block:
        recs['critico'] = parse_list(critico_block.group(1))
        
    # Importante
    importante_block = re.search(r'\*\*.*?(?:Importante|Pronto).*?\*\*(.*?)(?=\*\*|$)', text, re.DOTALL | re.IGNORECASE)
    if importante_block:
        recs['importante'] = parse_list(importante_block.group(1))
        
    # Menor
    menor_block = re.search(r'\*\*.*?(?:Menor|Posible|Baja).*?\*\*(.*?)(?=\*\*|$)', text, re.DOTALL | re.IGNORECASE)
    if menor_block:
        recs['menor'] = parse_list(menor_block.group(1))
        
    return recs

def export_to_html(content: str, output_path: Optional[Path] = None) -> Path:
    if output_path is None:
        output_dir = Path("output")
        output_dir.mkdir(exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = output_dir / f"analysis-{timestamp}.html"
    
    sections = parse_markdown_sections(content)
    categories = extract_failure_categories(sections.get('analisis', ''))
    recommendations = extract_recommendations(sections.get('recomendaciones', ''))
    
    # Contadores
    total_categories = len(categories)
    total_critical = len(recommendations['critico'])
    total_important = len(recommendations['importante'])
    
    # Colores
    gravedad_colors = {'alta': '#dc3545', 'media': '#ffc107', 'baja': '#28a745'}

    # Generar HTML Categorías
    categories_html = ""
    for cat in categories:
        g_lower = cat['gravedad'].lower()
        color = '#6c757d'
        if 'alta' in g_lower: color = gravedad_colors['alta']
        elif 'media' in g_lower: color = gravedad_colors['media']
        elif 'baja' in g_lower: color = gravedad_colors['baja']
        
        tests_html = "".join([f"<li class='test-item'>{t}</li>" for t in cat['tests']])
            
        categories_html += f"""
        <div class="failure-card">
            <div class="card-header">
                <h3 class="card-title">{cat['title']}</h3>
                <span class="badge" style="background: {color}">{cat['gravedad']}</span>
            </div>
            <div class="card-body">
                <div class="stat">
                    <span class="stat-label">Tests afectados:</span>
                    <span class="stat-value">{cat['cantidad'] or len(cat['tests'])}</span>
                </div>
                <div class="section"><strong>Causa probable:</strong><p>{cat['causa']}</p></div>
                <div class="section"><strong>Tests:</strong><ul class="test-list">{tests_html}</ul></div>
            </div>
        </div>
        """

    # Generar HTML Recomendaciones
    recommendations_html = ""
    rec_map = [
        ('critico', '🔴 Crítico', 'rec-critico'),
        ('importante', '🟡 Importante', 'rec-importante'),
        ('menor', '🟢 Menor', 'rec-menor')
    ]
    
    for key, title, css_class in rec_map:
        items = recommendations[key]
        if items:
            list_items = "".join([f"<li>{item}</li>" for item in items])
            recommendations_html += f"""
            <div class="rec-section {css_class}">
                <div class="rec-header"><h3>{title}</h3></div>
                <ul class="rec-list">{list_items}</ul>
            </div>"""

    # Resumen
    resumen_html = sections['resumen'].replace('\n', '<br>') if sections['resumen'] else "No disponible."
    raw_escaped = html.escape(sections['raw'])

    html_template = f"""<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Test Analysis Report</title>
    <style>
        :root {{ --primary: #667eea; --secondary: #764ba2; --bg: #f4f7f6; --text: #2d3748; }}
        body {{ font-family: system-ui, -apple-system, sans-serif; background: var(--bg); color: var(--text); padding: 2rem; line-height: 1.6; }}
        .container {{ max-width: 1200px; margin: 0 auto; }}
        .header {{ background: white; padding: 2rem; border-radius: 12px; box-shadow: 0 4px 6px rgba(0,0,0,0.05); margin-bottom: 2rem; }}
        .stats-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 1.5rem; margin-bottom: 2rem; }}
        .stat-card {{ background: white; padding: 1.5rem; border-radius: 12px; text-align: center; box-shadow: 0 2px 4px rgba(0,0,0,0.05); }}
        .stat-number {{ display: block; font-size: 2.5rem; font-weight: bold; color: var(--primary); }}
        .failure-card {{ background: white; border-radius: 12px; margin-bottom: 1.5rem; overflow: hidden; box-shadow: 0 2px 4px rgba(0,0,0,0.05); }}
        .card-header {{ background: #f8fafc; padding: 1rem 1.5rem; display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #e2e8f0; }}
        .card-body {{ padding: 1.5rem; }}
        .card-title {{ margin: 0; font-size: 1.25rem; }}
        .badge {{ padding: 0.25rem 0.75rem; border-radius: 999px; color: white; font-size: 0.875rem; font-weight: 600; }}
        .test-list {{ list-style: none; padding: 0; margin-top: 1rem; }}
        .test-item {{ background: #f1f5f9; padding: 0.5rem 1rem; margin-bottom: 0.5rem; border-radius: 6px; font-family: monospace; font-size: 0.9em; }}
        .rec-section {{ background: white; padding: 1.5rem; border-radius: 12px; margin-bottom: 1rem; border-left: 5px solid #ccc; }}
        .rec-critico {{ border-left-color: #dc3545; }}
        .rec-importante {{ border-left-color: #ffc107; }}
        .rec-menor {{ border-left-color: #28a745; }}
        .rec-header h3 {{ margin: 0; color: #4a5568; }}
        .rec-list {{ margin: 1rem 0 0 0; padding-left: 1.5rem; }}
        details {{ margin-top: 2rem; background: #e2e8f0; padding: 1rem; border-radius: 8px; }}
        pre {{ white-space: pre-wrap; word-wrap: break-word; font-size: 0.85rem; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>📊 Análisis de Tests Automatizados</h1>
            <p>{datetime.now().strftime("%d/%m/%Y %H:%M")}</p>
        </div>
        
        <div class="stats-grid">
            <div class="stat-card"><span class="stat-number">{total_categories}</span> Categorías</div>
            <div class="stat-card"><span class="stat-number" style="color:#dc3545">{total_critical}</span> Críticos</div>
            <div class="stat-card"><span class="stat-number" style="color:#ffc107">{total_important}</span> Importantes</div>
        </div>

        <div style="background:white; padding:2rem; border-radius:12px; margin-bottom:2rem; border-left: 5px solid var(--primary);">
            <h2>Resumen Ejecutivo</h2>
            <p>{resumen_html}</p>
        </div>

        <h2>Detalle de Fallos</h2>
        {categories_html if categories_html else '<p><em>No se encontraron categorías estructuradas.</em></p>'}

        <h2>Recomendaciones</h2>
        {recommendations_html if recommendations_html else '<p><em>Sin recomendaciones específicas.</em></p>'}
        
        <details>
            <summary>📂 Ver reporte original (Debug)</summary>
            <pre>{raw_escaped}</pre>
        </details>
    </div>
</body>
</html>"""
    
    output_path.write_text(html_template, encoding="utf-8")
    return output_path