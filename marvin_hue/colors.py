import random


class Color:
    """
    Classe para guardar as configurações de cores.
    """
    def __init__(self, red=254, green=254, blue=254, brightness=254):
        self.red = red
        self.green = green
        self.blue = blue
        self.brightness = brightness

    def __str__(self):
        return f"R: {self.red}, G: {self.green}, B: {self.blue}, Brightness: {self.brightness}"

    def to_dict(self):
        return {
            "red": self.red,
            "green": self.green,
            "blue": self.blue,
            "brightness": self.brightness,
        }

    @staticmethod
    def random_color(brightness=254):
        red = random.randint(0, 255)
        green = random.randint(0, 255)
        blue = random.randint(0, 255)
        brightness = random.randint(0, 254) if brightness == 254 else brightness
        return Color(red, green, blue, brightness)
