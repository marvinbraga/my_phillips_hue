from flask import Flask, jsonify, request, render_template
from marvin_hue.controllers import HueController
from marvin_hue.factories import LightConfigEnum
from decouple import config
import threading
import time

app = Flask(__name__, static_folder='web/static', template_folder='web/templates')
hue = HueController(ip_address=config("bridge_ip"))


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/configurations', methods=['GET'])
def get_configurations():
    configs = [{"name": item.name, "description": item.description} for item in LightConfigEnum]
    return jsonify(configs)


def apply_light_config(config_enum, transition_time_secs=0, duration_minutes=None):
    setup = config_enum.get_instance()
    hue.apply_light_config(setup, transition_time_secs)
    if duration_minutes:
        time.sleep(duration_minutes * 60)
        hue.apply_light_config(LightConfigEnum.SETUP_RELAXING.get_instance())


@app.route('/apply', methods=['POST'])
def apply_configuration():
    config_name = request.json.get('config_name')
    transition_time_secs = float(request.json.get('transition_time_secs', 0))

    duration_minutes = request.json.get('duration_minutes', None)

    config_enum = LightConfigEnum[config_name]
    t = threading.Thread(target=apply_light_config, args=(config_enum, transition_time_secs, duration_minutes))
    t.start()

    return jsonify({"message": f"Applying configuration {config_name}"})


if __name__ == '__main__':
    app.run(debug=True)
