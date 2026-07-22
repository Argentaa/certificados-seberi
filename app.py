import json
import os
import uuid
from datetime import date, datetime
from functools import wraps

import fitz  # PyMuPDF
from flask import (
    Flask,
    render_template,
    request,
    jsonify,
    session,
    redirect,
    url_for,
    send_file,
)
from PIL import Image, ImageDraw, ImageFont

from config import Config
from models import db, Registration

app = Flask(__name__)
app.config.from_object(Config)
db.init_app(app)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def hex_to_rgb(hex_color):
    hex_color = hex_color.lstrip("#")
    return tuple(int(hex_color[i : i + 2], 16) for i in (0, 2, 4))


TEMPLATE_CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "template_config.json")


def get_template_config():
    """Retorna as configurações do template (posição do nome)."""
    default = {"name_x": None, "name_y": None, "font_size": 44, "template_exists": False}
    if os.path.exists(TEMPLATE_CONFIG_PATH):
        try:
            with open(TEMPLATE_CONFIG_PATH) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return default


def save_template_config(config):
    """Salva as configurações do template."""
    with open(TEMPLATE_CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=2)


def require_admin(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("admin_logged_in"):
            return redirect(url_for("admin_login"))
        return f(*args, **kwargs)
    return decorated


def generate_certificate(registration):
    """Gera o certificado com o nome do participante.

    Prioridade:
    1. Se existir certificate_template.pdf → edita o PDF diretamente (PyMuPDF)
    2. Se existir certificate_template.png → usa como fundo (Pillow)
    3. Caso contrário → gera certificado completo via Pillow

    Retorna (caminho_arquivo, erro_ou_None).
    """
    output_dir = os.path.join(app.root_path, "certificates")
    os.makedirs(output_dir, exist_ok=True)

    template_pdf = os.path.join(app.root_path, "certificate_template.pdf")
    template_png = os.path.join(app.root_path, "certificate_template.png")

    name = registration.name.upper().strip()

    try:
        # ── 1) Template PDF ──────────────────────────────────────────────
        if os.path.exists(template_pdf):
            doc = fitz.open(template_pdf)
            page = doc[0]
            page_rect = page.rect

            # Encontra a linha "____________" (underline)
            underline_bbox = None
            blocks = page.get_text("dict")["blocks"]
            for block in blocks:
                if "lines" in block:
                    for line in block["lines"]:
                        text = "".join(s["text"] for s in line["spans"])
                        if "___" in text:  # underline tem 3+ underscores
                            underline_bbox = line["bbox"]
                            break
                if underline_bbox:
                    break

            if not underline_bbox:
                return None, "Linha '___' não encontrada no template PDF."

            x0, y0, x1, y1 = underline_bbox

            # Define tamanho da fonte (ajusta para nomes longos)
            fontsize = 30
            # Estima a largura do texto: ~0.55 * fonte * caracteres (aproximação helv)
            est_width = len(name) * fontsize * 0.55
            underline_width = x1 - x0
            while est_width > underline_width and fontsize > 14:
                fontsize -= 2
                est_width = len(name) * fontsize * 0.55

            # Insere o nome centralizado SOBRE a linha (sem retângulo branco)
            x_center = page_rect.width / 2
            y_center = (y0 + y1) / 2
            text_rect = fitz.Rect(
                x_center - 400, y_center - 30,
                x_center + 400, y_center + 30,
            )
            rc = page.insert_textbox(
                text_rect,
                name,
                fontname="helv",
                fontsize=fontsize,
                color=(0, 0, 0),
                align=1,  # center
                render_mode=0,
            )
            if rc < 0:
                return None, f"Falha ao inserir nome na página (rc={rc})."

            # Salva
            filename = f"certificado_{registration.id}_{uuid.uuid4().hex[:8]}.pdf"
            output_path = os.path.join(output_dir, filename)
            doc.save(output_path, garbage=4, deflate=True)
            doc.close()
            return output_path, None

        # ── 2) Template PNG ──────────────────────────────────────────────
        if os.path.exists(template_png):
            img = Image.open(template_png).convert("RGB")
            draw = ImageDraw.Draw(img)

            WIDTH, HEIGHT = img.size
            config = get_template_config()

            # Usa coordenadas salvas ou fallback para y=453
            name_y = config.get("name_y") or 453
            name_x = config.get("name_x")  # None = centralizado
            font_size = config.get("font_size", 44)

            try:
                font = ImageFont.truetype(
                    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", font_size
                )
            except (OSError, IOError):
                font = ImageFont.load_default()

            # Reduz fonte se nome for muito largo (max 55% da largura)
            bbox = draw.textbbox((0, 0), name, font=font)
            tw = bbox[2] - bbox[0]
            while tw > WIDTH * 0.55 and font_size > 20:
                font_size -= 2
                font = ImageFont.truetype(
                    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", font_size
                )
                bbox = draw.textbbox((0, 0), name, font=font)
                tw = bbox[2] - bbox[0]

            # Posiciona: se name_x foi definido, centraliza em torno dele
            if name_x:
                x_pos = name_x - tw // 2
            else:
                x_pos = (WIDTH - tw) // 2

            draw.text(
                (x_pos, name_y),
                name,
                fill=(0, 0, 0),  # preto
                font=font,
            )

            filename = f"certificado_{registration.id}_{uuid.uuid4().hex[:8]}.png"
            output_path = os.path.join(output_dir, filename)
            img.save(output_path, "PNG")
            return output_path, None

        # ── 3) Gera do zero ──────────────────────────────────────────────
        WIDTH, HEIGHT = 2480, 3508  # A4 em 300dpi
        GREEN = hex_to_rgb("#0d5e2e")
        LIGHT_GREEN = hex_to_rgb("#e8f5e9")
        GRAY = (80, 80, 80)
        WHITE = (255, 255, 255)

        img = Image.new("RGB", (WIDTH, HEIGHT), WHITE)
        draw = ImageDraw.Draw(img)

        # Moldura verde
        draw.rectangle([60, 60, WIDTH - 60, HEIGHT - 60], outline=GREEN, width=12)
        draw.rectangle([100, 100, WIDTH - 100, HEIGHT - 100], outline=GREEN, width=3)

        # Faixa decorativa superior
        draw.rectangle([0, 0, WIDTH, 280], fill=GREEN)
        draw.rectangle([0, HEIGHT - 120, WIDTH, HEIGHT], fill=GREEN)

        # Brasão/emblema
        draw.ellipse(
            [WIDTH // 2 - 90, 360, WIDTH // 2 + 90, 540],
            outline=GREEN, width=6,
        )
        draw.text(
            (WIDTH // 2, 450), "S",
            fill=GREEN,
            font=ImageFont.truetype(
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 100
            ),
            anchor="mm",
        )

        # Título
        try:
            font_title = ImageFont.truetype(
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 56
            )
            font_sub = ImageFont.truetype(
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 40
            )
            font_name = ImageFont.truetype(
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 100
            )
            font_body = ImageFont.truetype(
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 36
            )
        except (OSError, IOError):
            font_title = font_sub = font_name = font_body = ImageFont.load_default()

        draw.text(
            (WIDTH // 2, 640), "PREFEITURA MUNICIPAL DE SEBERI",
            fill=GREEN, font=font_title, anchor="mm",
        )
        draw.text(
            (WIDTH // 2, 700), "Administração 2021-2028",
            fill=GRAY, font=font_sub, anchor="mm",
        )

        # Corpo do certificado
        body_lines = [
            "CERTIFICADO DIGITAL",
            "",
            "Certificamos que",
        ]
        y = 880
        for line in body_lines:
            bbox = draw.textbbox((0, 0), line, font=font_sub if line else font_body)
            tw = bbox[2] - bbox[0]
            draw.text(((WIDTH - tw) / 2, y), line, fill=GRAY if line else None, font=font_sub if line else font_body)
            y += 60

        # Nome (grande)
        bbox = draw.textbbox((0, 0), name, font=font_name)
        tw = bbox[2] - bbox[0]
        while tw > WIDTH - 400 and font_name.size > 40:
            font_name = ImageFont.truetype(
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                font_name.size - 8,
            )
            bbox = draw.textbbox((0, 0), name, font=font_name)
            tw = bbox[2] - bbox[0]
        draw.text(((WIDTH - tw) / 2, y), name, fill=GREEN, font=font_name)

        # Linha abaixo do nome
        line_y = y + 90
        draw.line(
            [(WIDTH // 2 - 500, line_y), (WIDTH // 2 + 500, line_y)],
            fill=GREEN, width=3,
        )

        # Texto complementar
        complemento = [
            "pelos serviços prestados à comunidade, demonstrando",
            "dedicação e competência.",
        ]
        for i, linha in enumerate(complemento):
            bbox = draw.textbbox((0, 0), linha, font=font_body)
            tw = bbox[2] - bbox[0]
            draw.text(
                ((WIDTH - tw) / 2, line_y + 50 + i * 50),
                linha, fill=GRAY, font=font_body,
            )

        # Data
        meses = [
            "janeiro", "fevereiro", "março", "abril", "maio", "junho",
            "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
        ]
        hoje = date.today()
        data_texto = f"Seberi-RS, {hoje.day} de {meses[hoje.month - 1]} de {hoje.year}"
        bbox = draw.textbbox((0, 0), data_texto, font=font_body)
        tw = bbox[2] - bbox[0]
        draw.text(
            ((WIDTH - tw) / 2, line_y + 200),
            data_texto, fill=GRAY, font=font_body,
        )

        filename = f"certificado_{registration.id}_{uuid.uuid4().hex[:8]}.png"
        output_path = os.path.join(output_dir, filename)
        img.save(output_path, "PNG")
        return output_path, None

    except Exception as e:
        return None, f"Erro ao gerar certificado: {str(e)}"


# ---------------------------------------------------------------------------
# Rotas Públicas
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/register", methods=["POST"])
def api_register():
    data = request.get_json()
    if not data:
        return jsonify({"success": False, "message": "Dados inválidos."}), 400

    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip()

    if not name or len(name) < 3:
        return jsonify({"success": False, "message": "Nome deve ter pelo menos 3 caracteres."}), 400
    if not email or "@" not in email or "." not in email:
        return jsonify({"success": False, "message": "Email inválido."}), 400

    # Salva no banco
    reg = Registration(name=name, email=email)
    db.session.add(reg)
    db.session.commit()

    # Gera o certificado na hora
    cert_path, error = generate_certificate(reg)
    if error:
        reg.status = "failed"
        db.session.commit()
        return jsonify({
            "success": False,
            "message": f"Erro ao gerar certificado: {error}",
        }), 500

    # Atualiza registro
    relative_path = os.path.relpath(cert_path, app.root_path)
    reg.certificate_file = relative_path
    reg.status = "completed"
    reg.sent_count = 1
    reg.sent_at = datetime.utcnow()
    db.session.commit()

    download_url = url_for("download_certificate", filename=os.path.basename(cert_path), _external=False)

    return jsonify({
        "success": True,
        "message": "Certificado gerado com sucesso!",
        "download_url": download_url,
        "reg_id": reg.id,
    })


@app.route("/certificates/<filename>")
def download_certificate(filename):
    """Servir certificado para download."""
    cert_dir = os.path.join(app.root_path, "certificates")
    filepath = os.path.join(cert_dir, filename)
    if not os.path.exists(filepath):
        return jsonify({"success": False, "message": "Arquivo não encontrado."}), 404
    mime = "application/pdf" if filename.lower().endswith(".pdf") else "image/png"
    return send_file(filepath, mimetype=mime, as_attachment=True,
                     download_name=filename)


@app.route("/certificates/preview/<filename>")
def preview_certificate(filename):
    """Servir certificado para visualização inline."""
    cert_dir = os.path.join(app.root_path, "certificates")
    filepath = os.path.join(cert_dir, filename)
    # Se não estiver na pasta certificates, tenta a raiz (ex: template image)
    if not os.path.exists(filepath):
        filepath = os.path.join(app.root_path, filename)
    if not os.path.exists(filepath):
        return jsonify({"success": False, "message": "Arquivo não encontrado."}), 404
    mime = "application/pdf" if filename.lower().endswith(".pdf") else "image/png"
    return send_file(filepath, mimetype=mime)


# ---------------------------------------------------------------------------
# Rotas Administrativas
# ---------------------------------------------------------------------------

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        # Tenta JSON primeiro (API), depois form (HTML)
        if request.is_json:
            data = request.get_json(silent=True) or {}
            password = data.get("password", "")
        else:
            password = request.form.get("password", "")

        if password == app.config["ADMIN_PASSWORD"]:
            session["admin_logged_in"] = True
            if request.is_json:
                return jsonify({"success": True})
            return redirect(url_for("admin_dashboard"))
        if request.is_json:
            return jsonify({"success": False, "message": "Senha incorreta."}), 401
        return render_template("admin_login.html", error="Senha incorreta.")
    return render_template("admin_login.html")


@app.route("/admin/logout")
def admin_logout():
    session.pop("admin_logged_in", None)
    return redirect(url_for("admin_login"))


@app.route("/admin")
@require_admin
def admin_dashboard():
    return render_template("admin_dashboard.html")


@app.route("/admin/template")
@require_admin
def admin_template():
    """Página de configuração do template (upload + posição do nome)."""
    config = get_template_config()
    template_exists = os.path.exists(
        os.path.join(app.root_path, "certificate_template.png")
    )
    return render_template(
        "admin_template.html",
        config=config,
        template_exists=template_exists,
    )


@app.route("/admin/api/template", methods=["GET"])
@require_admin
def api_get_template():
    """Retorna info do template atual."""
    config = get_template_config()
    template_path = os.path.join(app.root_path, "certificate_template.png")
    exists = os.path.exists(template_path)
    return jsonify({
        "success": True,
        "exists": exists,
        "config": config,
    })


@app.route("/admin/api/template/image")
@require_admin
def api_template_image():
    """Serve a imagem do template para o coordinate picker."""
    template_path = os.path.join(app.root_path, "certificate_template.png")
    if not os.path.exists(template_path):
        return jsonify({"success": False, "message": "Template não encontrado."}), 404
    return send_file(template_path, mimetype="image/png")


@app.route("/admin/api/template/upload", methods=["POST"])
@require_admin
def api_upload_template():
    """Faz upload de uma nova imagem de template."""
    if "file" not in request.files:
        return jsonify({"success": False, "message": "Nenhum arquivo enviado."}), 400

    file = request.files["file"]
    if file.filename == "":
        return jsonify({"success": False, "message": "Nenhum arquivo selecionado."}), 400

    if not file.filename.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
        return jsonify({"success": False, "message": "Formato inválido. Use PNG, JPG ou WebP."}), 400

    # Salva como certificate_template.png
    template_path = os.path.join(app.root_path, "certificate_template.png")
    file.save(template_path)

    # Atualiza config
    config = get_template_config()
    config["template_exists"] = True
    save_template_config(config)

    return jsonify({
        "success": True,
        "message": "Template enviado com sucesso!",
        "width": 2560,
        "height": 1808,
    })


@app.route("/admin/api/template/position", methods=["POST"])
@require_admin
def api_save_position():
    """Salva a posição clicada para o nome."""
    data = request.get_json()
    if not data:
        return jsonify({"success": False, "message": "Dados inválidos."}), 400

    x = data.get("x")
    y = data.get("y")
    font_size = data.get("font_size", 44)

    if x is None or y is None:
        return jsonify({"success": False, "message": "Coordenadas x e y são obrigatórias."}), 400

    config = get_template_config()
    config["name_x"] = x
    config["name_y"] = y
    config["font_size"] = font_size
    save_template_config(config)

    return jsonify({
        "success": True,
        "message": f"Posição salva: x={x}, y={y}",
        "config": config,
    })


@app.route("/admin/api/registrations")
@require_admin
def api_list_registrations():
    search = request.args.get("search", "").strip().lower()

    query = Registration.query.order_by(Registration.created_at.desc())

    if search:
        query = query.filter(
            db.or_(
                Registration.name.ilike(f"%{search}%"),
                Registration.email.ilike(f"%{search}%"),
            )
        )

    registrations = query.all()
    return jsonify({
        "success": True,
        "registrations": [r.to_dict() for r in registrations],
    })


@app.route("/admin/api/delete/<int:reg_id>", methods=["DELETE"])
@require_admin
def api_delete_registration(reg_id):
    reg = db.session.get(Registration, reg_id)
    if not reg:
        return jsonify({"success": False, "message": "Registro não encontrado."}), 404

    # Remove arquivo do certificado se existir
    if reg.certificate_file:
        cert_path = os.path.join(app.root_path, reg.certificate_file)
        if os.path.exists(cert_path):
            os.remove(cert_path)

    db.session.delete(reg)
    db.session.commit()
    return jsonify({"success": True, "message": "Registro excluído."})


# ---------------------------------------------------------------------------
# Inicialização
# ---------------------------------------------------------------------------

@app.cli.command("init-db")
def init_db():
    with app.app_context():
        db.create_all()
        print("✅ Banco de dados inicializado!")


@app.before_request
def create_tables():
    if not hasattr(app, "_tables_created"):
        with app.app_context():
            db.create_all()
        app._tables_created = True


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
