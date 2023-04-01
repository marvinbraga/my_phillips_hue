from time import sleep
from decouple import config

from controlles import HueController
from factories import LightConfigEnum

hue = HueController(ip_address=config("bridge_ip"))


def test(config_enum):
    setup = config_enum.get_instance()
    print(f"Name: {setup}, Description: {config_enum.description}")
    hue.apply_light_config(setup, transition_time_secs=3)


def test_all():
    for config_enum in LightConfigEnum:
        test(config_enum)
        sleep(7)


if __name__ == '__main__':
    # test(LightConfigEnum.SETUP_RELAXING)
    test_all()
