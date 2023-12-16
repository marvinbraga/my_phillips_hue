from flask import Flask, jsonify, request, render_template

from marvin_hue.basics import LightSetupsManager
from marvin_hue.controllers import HueController
from marvin_hue.factories import LightConfigEnum
from decouple import config
import threading
import time

app = Flask(__name__, static_folder='web/static', template_folder='web/templates')
hue = HueController(ip_address=config("bridge_ip"))
manager = LightSetupsManager(".res/setups.json")


def sort_items():
    unique_configs = {item.name: item for item in manager.configs}.values()
    sorted_list = sorted(unique_configs, key=lambda item: item.name)
    result = [{"name": item.name, "description": item.description} for item in sorted_list]
    return result


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/configurations', methods=['GET'])
def get_configurations():
    return jsonify(sort_items())


def apply_light_config(config_enum, transition_time_secs=0, duration_minutes=None):
    """
    Método para aplicar as configurações selecionadas.
    """

    setup = config_enum
    hue.apply_light_config(setup, transition_time_secs)
    if duration_minutes:
        time.sleep(duration_minutes * 60)
        hue.apply_light_config(LightConfigEnum.SETUP_RELAXING.get_instance())


@app.route('/apply', methods=['POST'])
def apply_configuration():
    """
    Endpoint para aplicar a configuração selecionada.
    """

    # Recupera as informações da request.
    config_name = request.json.get('config_name')
    transition_time_secs = float(request.json.get('transition_time_secs', 0))
    duration_minutes = request.json.get('duration_minutes', None)

    # Recupera a configuração de luz do Manager.
    config_enum = manager.get_config(config_name)

    # Aplica a configuração.
    t = threading.Thread(target=apply_light_config, args=(config_enum, transition_time_secs, duration_minutes))
    t.start()

    # Retornar a informação de execução da tarefa.
    return jsonify({
        "message": f"Applying configuration {config_name}",
        "details": {
            "config_name": config_name,
            "transition_time_secs": transition_time_secs,
            "duration_minutes": duration_minutes
        }
    })


if __name__ == '__main__':
    app.run(debug=True)
