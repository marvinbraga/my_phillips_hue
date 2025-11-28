"""
Módulo de espelhamento de tela para Philips Hue.
Captura regiões da tela e aplica as cores dominantes às lâmpadas configuradas.
"""

import json
import threading
import time
from dataclasses import dataclass
from typing import Callable

import mss
from PIL import Image

from marvin_hue.colors import Color
from marvin_hue.controllers import HueController
from marvin_hue.utils import RGBtoXYAdapter


@dataclass
class ScreenRegion:
    """Define uma região da tela para captura."""
    x: int
    y: int
    width: int
    height: int


class ScreenMirror:
    """
    Controlador de espelhamento de tela.
    Captura regiões da tela e aplica as cores às lâmpadas Hue.
    """

    # Mapeamento de posições para regiões da tela (em porcentagem)
    POSITION_REGIONS = {
        "left": (0.0, 0.2, 0.15, 0.6),        # x, y, width, height (em %)
        "right": (0.85, 0.2, 0.15, 0.6),
        "top": (0.2, 0.0, 0.6, 0.15),
        "bottom": (0.2, 0.85, 0.6, 0.15),
        "top-left": (0.0, 0.0, 0.25, 0.25),
        "top-right": (0.75, 0.0, 0.25, 0.25),
        "bottom-left": (0.0, 0.75, 0.25, 0.25),
        "bottom-right": (0.75, 0.75, 0.25, 0.25),
        "center": (0.25, 0.25, 0.5, 0.5),  # Região maior no centro
        "ambient": (0.0, 0.0, 1.0, 1.0),       # Tela inteira
    }

    def __init__(self, hue_controller: HueController, positions_file: str = ".res/light_positions.json"):
        self.hue = hue_controller
        self.positions_file = positions_file
        self.running = False
        self.thread: threading.Thread | None = None
        self.fps = 10  # Reduzido para não sobrecarregar a bridge Hue
        self.brightness = 200
        self.saturation_boost = 1.2
        self.smoothing_factor = 0.5  # Fator de suavização (0.0-1.0, menor = mais suave)
        self.transition_time = 1  # Tempo de transição em décimos de segundo (100ms)
        self._on_status_change: Callable[[dict], None] | None = None
        self._current_colors: dict[str, tuple] = {}
        self._target_colors: dict[str, tuple] = {}  # Cores alvo para interpolação
        self._smoothed_colors: dict[str, tuple] = {}  # Cores suavizadas

    def load_light_positions(self) -> list[dict]:
        """Carrega a configuração de posicionamento das lâmpadas."""
        try:
            with open(self.positions_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return [l for l in data.get("lights", []) if l.get("enabled") and l.get("position") != "none"]
        except (FileNotFoundError, json.JSONDecodeError):
            return []

    def get_screen_region(self, position: str, screen_width: int, screen_height: int) -> ScreenRegion:
        """Calcula a região da tela para uma posição."""
        if position not in self.POSITION_REGIONS:
            # Fallback para ambient
            position = "ambient"

        x_pct, y_pct, w_pct, h_pct = self.POSITION_REGIONS[position]
        return ScreenRegion(
            x=int(screen_width * x_pct),
            y=int(screen_height * y_pct),
            width=int(screen_width * w_pct),
            height=int(screen_height * h_pct)
        )

    def get_dominant_color(self, image: Image.Image, region: ScreenRegion) -> tuple[int, int, int]:
        """Extrai a cor dominante de uma região da imagem."""
        # Recorta a região
        cropped = image.crop((
            region.x,
            region.y,
            region.x + region.width,
            region.y + region.height
        ))

        # Redimensiona para amostragem maior (32x32 = 1024 pixels)
        small = cropped.resize((32, 32), Image.Resampling.LANCZOS)

        # Filtra pixels e calcula média ponderada
        pixels = list(small.getdata())

        # Filtra pixels muito escuros ou muito claros (UI elements, bordas)
        filtered_pixels = []
        for p in pixels:
            brightness = (p[0] + p[1] + p[2]) / 3
            # Ignora pixels muito escuros (<15) ou quase brancos (>240)
            if 15 < brightness < 240:
                # Dá mais peso para pixels mais saturados (coloridos)
                saturation = max(p[0], p[1], p[2]) - min(p[0], p[1], p[2])
                weight = 1 + (saturation / 255)  # 1.0 a 2.0
                filtered_pixels.append((p, weight))

        if not filtered_pixels:
            # Fallback: usa todos os pixels se filtro removeu tudo
            filtered_pixels = [(p, 1) for p in pixels]

        # Média ponderada
        total_weight = sum(w for _, w in filtered_pixels)
        r = int(sum(p[0] * w for p, w in filtered_pixels) / total_weight)
        g = int(sum(p[1] * w for p, w in filtered_pixels) / total_weight)
        b = int(sum(p[2] * w for p, w in filtered_pixels) / total_weight)

        # Aplica boost de saturação
        r, g, b = self._boost_saturation(r, g, b)

        return r, g, b

    def _boost_saturation(self, r: int, g: int, b: int) -> tuple[int, int, int]:
        """Aumenta a saturação da cor para melhor efeito visual."""
        # Converte para HSL simplificado
        max_c = max(r, g, b)
        min_c = min(r, g, b)
        avg = (max_c + min_c) // 2

        if max_c == min_c:
            return r, g, b  # Cinza, sem saturação

        # Aumenta a diferença do valor médio
        factor = self.saturation_boost
        r = int(avg + (r - avg) * factor)
        g = int(avg + (g - avg) * factor)
        b = int(avg + (b - avg) * factor)

        # Clamp values
        r = max(0, min(255, r))
        g = max(0, min(255, g))
        b = max(0, min(255, b))

        return r, g, b

    def _interpolate_color(self, current: tuple[int, int, int], target: tuple[int, int, int]) -> tuple[int, int, int]:
        """Interpola suavemente entre a cor atual e a cor alvo."""
        factor = self.smoothing_factor
        r = int(current[0] + (target[0] - current[0]) * factor)
        g = int(current[1] + (target[1] - current[1]) * factor)
        b = int(current[2] + (target[2] - current[2]) * factor)
        return (r, g, b)

    def _color_changed_significantly(self, light_name: str, new_color: tuple[int, int, int], threshold: int = 15) -> bool:
        """Verifica se a cor mudou o suficiente para justificar atualização."""
        if light_name not in self._smoothed_colors:
            return True
        old = self._smoothed_colors[light_name]
        diff = abs(new_color[0] - old[0]) + abs(new_color[1] - old[1]) + abs(new_color[2] - old[2])
        return diff > threshold

    def _apply_color_to_light(self, light_name: str, r: int, g: int, b: int):
        """Aplica uma cor a uma lâmpada específica."""
        target = (r, g, b)

        # Interpola a cor para suavizar a transição
        if light_name in self._smoothed_colors:
            current = self._smoothed_colors[light_name]
            smoothed = self._interpolate_color(current, target)
        else:
            smoothed = target

        # Só envia para a lâmpada se a cor mudou significativamente
        if not self._color_changed_significantly(light_name, smoothed):
            return

        # Atualiza a cor suavizada
        self._smoothed_colors[light_name] = smoothed

        try:
            xy = RGBtoXYAdapter.convert(smoothed[0], smoothed[1], smoothed[2])
            light = self.hue._get_light_by_name(light_name)
            if light:
                # API Hue aceita transitiontime como inteiro (décimos de segundo)
                light.transitiontime = int(round(self.transition_time))
                light.xy = xy
                light.brightness = self.brightness
        except Exception:
            pass  # Ignora erros de comunicação com lâmpadas individuais

    def _mirror_loop(self):
        """Loop principal de captura e aplicação de cores."""
        with mss.mss() as sct:
            # Obtém informações do monitor principal
            monitor = sct.monitors[1]  # Monitor principal
            screen_width = monitor["width"]
            screen_height = monitor["height"]

            frame_time = 1.0 / self.fps

            while self.running:
                start_time = time.time()

                # Captura a tela
                screenshot = sct.grab(monitor)
                image = Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")

                # Carrega configuração de lâmpadas
                lights = self.load_light_positions()

                # Agrupa lâmpadas por posição para otimizar
                position_lights: dict[str, list[str]] = {}
                for light in lights:
                    pos = light["position"]
                    if pos not in position_lights:
                        position_lights[pos] = []
                    position_lights[pos].append(light["name"])

                # Processa cada posição
                for position, light_names in position_lights.items():
                    region = self.get_screen_region(position, screen_width, screen_height)
                    r, g, b = self.get_dominant_color(image, region)

                    # Aplica a cor a todas as lâmpadas desta posição
                    for light_name in light_names:
                        self._target_colors[light_name] = (r, g, b)
                        self._apply_color_to_light(light_name, r, g, b)
                        # Atualiza cores atuais com as suavizadas para exibição
                        if light_name in self._smoothed_colors:
                            self._current_colors[light_name] = self._smoothed_colors[light_name]
                        else:
                            self._current_colors[light_name] = (r, g, b)

                # Notifica mudança de status se houver callback
                if self._on_status_change:
                    self._on_status_change({
                        "running": True,
                        "fps": self.fps,
                        "colors": self._current_colors.copy()
                    })

                # Aguarda para manter o FPS
                elapsed = time.time() - start_time
                if elapsed < frame_time:
                    time.sleep(frame_time - elapsed)

    def start(self, fps: int = 25, brightness: int = 200):
        """Inicia o espelhamento de tela."""
        if self.running:
            return False

        self.fps = fps
        self.brightness = brightness
        self.running = True
        self.thread = threading.Thread(target=self._mirror_loop, daemon=True)
        self.thread.start()
        return True

    def stop(self):
        """Para o espelhamento de tela."""
        self.running = False
        if self.thread:
            self.thread.join(timeout=2.0)
            self.thread = None
        self._current_colors.clear()
        self._target_colors.clear()
        self._smoothed_colors.clear()
        return True

    def is_running(self) -> bool:
        """Verifica se o espelhamento está ativo."""
        return self.running

    def get_status(self) -> dict:
        """Retorna o status atual do espelhamento."""
        return {
            "running": self.running,
            "fps": self.fps,
            "brightness": self.brightness,
            "colors": self._current_colors.copy()
        }

    def set_status_callback(self, callback: Callable[[dict], None]):
        """Define callback para mudanças de status."""
        self._on_status_change = callback
