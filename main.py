from time import sleep
from decouple import config

from controlles import HueController
from setups import Setups

bridge_ip = config("bridge_ip")

# Exemplo de uso
hue = HueController(bridge_ip)
setups = Setups()

names = setups.list_names()
print(names)


def test_all():
    for name in names:
        print(name)
        hue.apply_light_config(
            setups.get(name)
        )
        sleep(7)


def test(name):
    print(name)
    hue.apply_light_config(setups.get(name))


if __name__ == '__main__':
    test("morning_eye_soothing")
    # test_all()
