import os
import re
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, List, Tuple


def export_to_markdown(content: str, output_path: Optional[Path] = None) -> Path:
    """
    Exporta el análisis a un archivo Markdown.
    
    Args:
        content: Contenido del análisis en formato Markdown
        output_path: Path personalizado. Si es None, usa output/analysis-{timestamp}.md
    
    Returns:
        Path al archivo generado
    """
    if output_path is None:
        # Crear directorio output si no existe
        output_dir = Path("output")
        output_dir.mkdir(exist_ok=True)
        
        # Generar nombre con timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = output_dir / f"analysis-{timestamp}.md"
    
    # Escribir el archivo
    output_path.write_text(content, encoding="utf-8")
    
    return output_path


def parse_markdown_sections(content: str) -> Dict[str, str]:
    """
    Parsea el contenido markdown y extrae secciones clave.
    
    Returns:
        Dict con secciones: resumen, analisis, recomendaciones
    """
    sections = {
        'resumen': '',
        'analisis': '',
        'recomendaciones': '',
        'raw': content
    }
    
    # Buscar Resumen Ejecutivo
    resumen_match = re.search(r'#+ Resumen Ejecutivo\s*\n+(.*?)(?=\n#|$)', content, re.DOTALL | re.IGNORECASE)
    if resumen_match:
        sections['resumen'] = resumen_match.group(1).strip()
    
    # Buscar Análisis de Fallos
    analisis_match = re.search(r'#+ An[aá]lisis de Fallos\s*\n+(.*?)(?=\n# Recomendaciones|$)', content, re.DOTALL | re.IGNORECASE)
    if analisis_match:
        sections['analisis'] = analisis_match.group(1).strip()
    
    # Buscar Recomendaciones
    recomendaciones_match = re.search(r'#+ Recomendaciones.*?\n+(.*?)$', content, re.DOTALL | re.IGNORECASE)
    if recomendaciones_match:
        sections['recomendaciones'] = recomendaciones_match.group(1).strip()
    
    return sections


def extract_failure_categories(analisis_text: str) -> List[Dict[str, str]]:
    """
    Extrae categorías de fallos del análisis.
    
    Returns:
        Lista de diccionarios con información de cada categoría
    """
    categories = []
    
    # Dividir por ## (cada categoría)
    category_blocks = re.split(r'\n## ', analisis_text)
    
    for block in category_blocks[1:]:  # Saltar el primer elemento vacío
        lines = block.strip().split('\n')
        if not lines:
            continue
            
        # Título de la categoría
        title = lines[0].strip()
        
        # Extraer gravedad
        gravedad = 'Media'
        gravedad_match = re.search(r'\*\*Gravedad:\*\*\s*(\w+)', block, re.IGNORECASE)
        if gravedad_match:
            gravedad = gravedad_match.group(1)
        
        # Extraer cantidad
        cantidad = ''
        cantidad_match = re.search(r'\*\*Cantidad:\*\*\s*(.+)', block, re.IGNORECASE)
        if cantidad_match:
            cantidad = cantidad_match.group(1).strip()
        
        # Extraer causa probable
        causa = ''
        causa_match = re.search(r'\*\*Causa probable:\*\*\s*\n+(.*?)(?=\n\*\*|$)', block, re.DOTALL | re.IGNORECASE)
        if causa_match:
            causa = causa_match.group(1).strip()
        
        # Extraer tests afectados
        tests = []
        tests_section = re.search(r'\*\*Tests afectados:\*\*\s*\n+(.*?)(?=\n\*\*|$)', block, re.DOTALL | re.IGNORECASE)
        if tests_section:
            test_lines = tests_section.group(1).strip().split('\n')
            tests = [line.strip('- ').strip() for line in test_lines if line.strip().startswith('-')]
        
        categories.append({
            'title': title,
            'gravedad': gravedad,
            'cantidad': cantidad,
            'causa': causa,
            'tests': tests,
            'raw': block
        })
    
    return categories


def extract_recommendations(recomendaciones_text: str) -> Dict[str, List[str]]:
    """
    Extrae recomendaciones por prioridad.
    
    Returns:
        Dict con listas de recomendaciones: critico, importante, menor
    """
    recs = {
        'critico': [],
        'importante': [],
        'menor': []
    }
    
    # Buscar crítico
    critico_match = re.search(r'🔴.*?Cr[ií]tico.*?\n+(.*?)(?=\n\*\*🟡|\n\*\*🟢|$)', recomendaciones_text, re.DOTALL | re.IGNORECASE)
    if critico_match:
        lines = critico_match.group(1).strip().split('\n')
        recs['critico'] = [line.strip('- ').strip() for line in lines if line.strip().startswith('-')]
    
    # Buscar importante
    importante_match = re.search(r'🟡.*?Importante.*?\n+(.*?)(?=\n\*\*🟢|$)', recomendaciones_text, re.DOTALL | re.IGNORECASE)
    if importante_match:
        lines = importante_match.group(1).strip().split('\n')
        recs['importante'] = [line.strip('- ').strip() for line in lines if line.strip().startswith('-')]
    
    # Buscar menor
    menor_match = re.search(r'🟢.*?Menor.*?\n+(.*?)$', recomendaciones_text, re.DOTALL | re.IGNORECASE)
    if menor_match:
        lines = menor_match.group(1).strip().split('\n')
        recs['menor'] = [line.strip('- ').strip() for line in lines if line.strip().startswith('-')]
    
    return recs


def export_to_html(content: str, output_path: Optional[Path] = None) -> Path:
    """
    Exporta el análisis a un archivo HTML visual y moderno.
    
    Args:
        content: Contenido del análisis en formato Markdown
        output_path: Path personalizado. Si es None, usa output/analysis-{timestamp}.html
    
    Returns:
        Path al archivo generado
    """
    if output_path is None:
        output_dir = Path("output")
        output_dir.mkdir(exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = output_dir / f"analysis-{timestamp}.html"
    
    # Parsear contenido
    sections = parse_markdown_sections(content)
    categories = extract_failure_categories(sections.get('analisis', ''))
    recommendations = extract_recommendations(sections.get('recomendaciones', ''))
    
    # Contar totales
    total_categories = len(categories)
    total_critical = len(recommendations.get('critico', []))
    total_important = len(recommendations.get('importante', []))
    
    # Mapeo de gravedad a colores
    gravedad_colors = {
        'alta': '#dc3545',
        'media': '#ffc107',
        'baja': '#28a745'
    }
    
    # Generar HTML de categorías
    categories_html = ""
    for cat in categories:
        gravedad_lower = cat['gravedad'].lower()
        color = gravedad_colors.get(gravedad_lower, '#6c757d')
        
        tests_html = ""
        for test in cat['tests'][:5]:  # Máximo 5 tests mostrados
            tests_html += f"<li class='test-item'>{test}</li>"
        
        if len(cat['tests']) > 5:
            tests_html += f"<li class='test-item more'>+ {len(cat['tests']) - 5} tests más</li>"
        
        categories_html += f"""
        <div class="failure-card">
            <div class="card-header">
                <h3 class="card-title">{cat['title']}</h3>
                <span class="badge badge-{gravedad_lower}" style="background: {color}">
                    {cat['gravedad']}
                </span>
            </div>
            <div class="card-body">
                <div class="stat">
                    <span class="stat-label">Tests afectados:</span>
                    <span class="stat-value">{cat['cantidad'] or len(cat['tests'])}</span>
                </div>
                
                {'<div class="section"><strong>Causa probable:</strong><p>' + cat['causa'] + '</p></div>' if cat['causa'] else ''}
                
                {f'<div class="section"><strong>Tests afectados:</strong><ul class="test-list">{tests_html}</ul></div>' if cat['tests'] else ''}
            </div>
        </div>
        """
    
    # Generar HTML de recomendaciones
    recommendations_html = ""
    
    if recommendations['critico']:
        recommendations_html += """
        <div class="rec-section rec-critical">
            <div class="rec-header">
                <span class="rec-icon">🔴</span>
                <h3>Crítico - Acción Inmediata</h3>
            </div>
            <ul class="rec-list">
        """
        for rec in recommendations['critico']:
            recommendations_html += f"<li>{rec}</li>"
        recommendations_html += "</ul></div>"
    
    if recommendations['importante']:
        recommendations_html += """
        <div class="rec-section rec-important">
            <div class="rec-header">
                <span class="rec-icon">🟡</span>
                <h3>Importante - Resolver Pronto</h3>
            </div>
            <ul class="rec-list">
        """
        for rec in recommendations['importante']:
            recommendations_html += f"<li>{rec}</li>"
        recommendations_html += "</ul></div>"
    
    if recommendations['menor']:
        recommendations_html += """
        <div class="rec-section rec-minor">
            <div class="rec-header">
                <span class="rec-icon">🟢</span>
                <h3>Menor - Revisar Cuando Sea Posible</h3>
            </div>
            <ul class="rec-list">
        """
        for rec in recommendations['menor']:
            recommendations_html += f"<li>{rec}</li>"
        recommendations_html += "</ul></div>"
    
    # Plantilla HTML
    html_template = f"""<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Análisis de Tests - {datetime.now().strftime("%d/%m/%Y %H:%M")}</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Roboto', 'Oxygen', 'Ubuntu', 'Cantarell', sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 40px 20px;
            color: #2d3748;
        }}
        
        .container {{
            max-width: 1400px;
            margin: 0 auto;
        }}
        
        .header {{
            background: white;
            border-radius: 20px;
            padding: 40px;
            margin-bottom: 30px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
        }}
        
        .header h1 {{
            font-size: 2.5em;
            color: #1a202c;
            margin-bottom: 10px;
            display: flex;
            align-items: center;
            gap: 15px;
        }}
        
        .header .timestamp {{
            color: #718096;
            font-size: 0.9em;
            margin-top: 10px;
        }}
        
        .stats-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }}
        
        .stat-card {{
            background: white;
            border-radius: 15px;
            padding: 25px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.2);
            transition: transform 0.3s ease, box-shadow 0.3s ease;
        }}
        
        .stat-card:hover {{
            transform: translateY(-5px);
            box-shadow: 0 15px 40px rgba(0,0,0,0.3);
        }}
        
        .stat-card .stat-number {{
            font-size: 3em;
            font-weight: bold;
            display: block;
            margin-bottom: 5px;
        }}
        
        .stat-card .stat-label {{
            color: #718096;
            font-size: 1em;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}
        
        .stat-card.critical .stat-number {{ color: #dc3545; }}
        .stat-card.important .stat-number {{ color: #ffc107; }}
        .stat-card.categories .stat-number {{ color: #667eea; }}
        
        .section {{
            background: white;
            border-radius: 15px;
            padding: 30px;
            margin-bottom: 30px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.2);
        }}
        
        .section h2 {{
            font-size: 2em;
            color: #1a202c;
            margin-bottom: 20px;
            padding-bottom: 15px;
            border-bottom: 3px solid #667eea;
        }}
        
        .summary-box {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 30px;
            border-radius: 15px;
            font-size: 1.1em;
            line-height: 1.8;
            margin-bottom: 30px;
            box-shadow: 0 10px 30px rgba(102, 126, 234, 0.4);
        }}
        
        .failure-card {{
            background: white;
            border-radius: 12px;
            margin-bottom: 25px;
            overflow: hidden;
            border-left: 5px solid #667eea;
            box-shadow: 0 5px 15px rgba(0,0,0,0.1);
            transition: transform 0.2s ease, box-shadow 0.2s ease;
        }}
        
        .failure-card:hover {{
            transform: translateX(5px);
            box-shadow: 0 8px 25px rgba(0,0,0,0.15);
        }}
        
        .card-header {{
            background: #f7fafc;
            padding: 20px 25px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 2px solid #e2e8f0;
        }}
        
        .card-title {{
            font-size: 1.3em;
            color: #2d3748;
            font-weight: 600;
        }}
        
        .badge {{
            padding: 8px 16px;
            border-radius: 20px;
            color: white;
            font-weight: bold;
            font-size: 0.85em;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}
        
        .badge-alta {{ background: #dc3545; }}
        .badge-media {{ background: #ffc107; color: #000; }}
        .badge-baja {{ background: #28a745; }}
        
        .card-body {{
            padding: 25px;
        }}
        
        .card-body .section {{
            background: transparent;
            padding: 15px 0;
            margin: 15px 0;
            border-bottom: 1px solid #e2e8f0;
            box-shadow: none;
        }}
        
        .card-body .section:last-child {{
            border-bottom: none;
        }}
        
        .stat {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 12px 0;
        }}
        
        .stat-label {{
            color: #4a5568;
            font-weight: 500;
        }}
        
        .stat-value {{
            color: #667eea;
            font-weight: bold;
            font-size: 1.1em;
        }}
        
        .test-list {{
            list-style: none;
            margin-top: 10px;
        }}
        
        .test-item {{
            padding: 10px 15px;
            background: #f7fafc;
            margin-bottom: 8px;
            border-radius: 8px;
            border-left: 3px solid #667eea;
            font-family: 'Courier New', monospace;
            font-size: 0.9em;
        }}
        
        .test-item.more {{
            background: #e2e8f0;
            color: #4a5568;
            font-style: italic;
            border-left-color: #a0aec0;
        }}
        
        .rec-section {{
            background: white;
            border-radius: 12px;
            padding: 25px;
            margin-bottom: 20px;
            border-left: 5px solid;
            box-shadow: 0 5px 15px rgba(0,0,0,0.1);
        }}
        
        .rec-critical {{ border-left-color: #dc3545; }}
        .rec-important {{ border-left-color: #ffc107; }}
        .rec-minor {{ border-left-color: #28a745; }}
        
        .rec-header {{
            display: flex;
            align-items: center;
            gap: 15px;
            margin-bottom: 20px;
        }}
        
        .rec-icon {{
            font-size: 2em;
        }}
        
        .rec-header h3 {{
            color: #2d3748;
            font-size: 1.3em;
            margin: 0;
        }}
        
        .rec-list {{
            list-style: none;
        }}
        
        .rec-list li {{
            padding: 15px 20px;
            background: #f7fafc;
            margin-bottom: 10px;
            border-radius: 8px;
            position: relative;
            padding-left: 50px;
        }}
        
        .rec-list li:before {{
            content: "→";
            position: absolute;
            left: 20px;
            font-size: 1.5em;
            color: #667eea;
            font-weight: bold;
        }}
        
        .footer {{
            text-align: center;
            margin-top: 50px;
            padding: 30px;
            background: rgba(255,255,255,0.1);
            border-radius: 15px;
            color: white;
            backdrop-filter: blur(10px);
        }}
        
        @media print {{
            body {{
                background: white;
                padding: 20px;
            }}
            
            .header, .section, .failure-card, .rec-section {{
                box-shadow: none;
                break-inside: avoid;
            }}
        }}
        
        @media (max-width: 768px) {{
            .stats-grid {{
                grid-template-columns: 1fr;
            }}
            
            .header h1 {{
                font-size: 1.8em;
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <!-- Header -->
        <div class="header">
            <h1>
                <span>📊</span>
                Análisis de Fallos de Tests
            </h1>
            <div class="timestamp">
                📅 Generado el {datetime.now().strftime("%d/%m/%Y a las %H:%M:%S")}
            </div>
        </div>
        
        <!-- Stats -->
        <div class="stats-grid">
            <div class="stat-card categories">
                <span class="stat-number">{total_categories}</span>
                <span class="stat-label">Categorías de Fallos</span>
            </div>
            <div class="stat-card critical">
                <span class="stat-number">{total_critical}</span>
                <span class="stat-label">Acciones Críticas</span>
            </div>
            <div class="stat-card important">
                <span class="stat-number">{total_important}</span>
                <span class="stat-label">Acciones Importantes</span>
            </div>
        </div>
        
        <!-- Resumen Ejecutivo -->
        {f'<div class="summary-box"><strong>📋 Resumen Ejecutivo</strong><br><br>{sections["resumen"]}</div>' if sections['resumen'] else ''}
        
        <!-- Análisis de Fallos -->
        <div class="section">
            <h2>🔍 Análisis Detallado de Fallos</h2>
            {categories_html if categories_html else '<p>No se encontraron categorías de fallos en el análisis.</p>'}
        </div>
        
        <!-- Recomendaciones -->
        {f'<div class="section"><h2>✅ Recomendaciones Priorizadas</h2>{recommendations_html}</div>' if recommendations_html else ''}
        
        <!-- Footer -->
        <div class="footer">
            <p><strong>🤖 AI Test Failure Analyzer</strong></p>
            <p>Powered by Ollama</p>
        </div>
    </div>
</body>
</html>"""
    
    # Escribir el archivo
    output_path.write_text(html_template, encoding="utf-8")
    
    return output_path
