"""Browser fingerprint rotation for stealth and anti-detection."""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Literal

# Common user agents by browser/OS
USER_AGENTS = {
    "chrome_windows": [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36",
    ],
    "chrome_linux": [
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    ],
    "chrome_mac": [
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    ],
    "firefox_windows": [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0",
    ],
    "firefox_linux": [
        "Mozilla/5.0 (X11; Linux x86_64; rv:121.0) Gecko/20100101 Firefox/121.0",
        "Mozilla/5.0 (X11; Linux x86_64; rv:120.0) Gecko/20100101 Firefox/120.0",
    ],
    "firefox_mac": [
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:121.0) Gecko/20100101 Firefox/121.0",
    ],
    "safari_mac": [
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15",
    ],
    "edge_windows": [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36 Edg/119.0.0.0",
    ],
}

# Screen resolutions
SCREEN_RESOLUTIONS = [
    (1920, 1080), (1366, 768), (1536, 864), (1440, 900),
    (1280, 720), (1600, 900), (2560, 1440), (3840, 2160),
]

# Timezones
TIMEZONES = [
    "Europe/Berlin", "Europe/London", "Europe/Paris", "America/New_York",
    "America/Los_Angeles", "America/Chicago", "Europe/Madrid", "Europe/Rome",
    "Europe/Amsterdam", "Europe/Stockholm", "Europe/Vienna", "Europe/Warsaw",
]

# Languages
LANGUAGES = [
    "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7",
    "en-US,en;q=0.9",
    "en-GB,en;q=0.9",
    "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
    "es-ES,es;q=0.9,en;q=0.8",
    "it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7",
    "nl-NL,nl;q=0.9,en-US;q=0.8,en;q=0.7",
    "pl-PL,pl;q=0.9,en-US;q=0.8,en;q=0.7",
]

# Platform strings
PLATFORMS = {
    "windows": "Win32",
    "linux": "Linux x86_64",
    "mac": "MacIntel",
}

# CPU cores (common values)
CPU_CORES = [2, 4, 6, 8, 12, 16]

# Device memory (GB)
DEVICE_MEMORY = [2, 4, 8, 16, 32]

# Color depth
COLOR_DEPTHS = [24, 30]


@dataclass
class Fingerprint:
    """Complete browser fingerprint."""
    user_agent: str
    browser_type: Literal["chromium", "firefox", "webkit"]
    platform: str
    screen_width: int
    screen_height: int
    timezone: str
    language: str
    cpu_cores: int
    device_memory: int
    color_depth: int
    webgl_vendor: str
    webgl_renderer: str
    canvas_noise: float
    audio_noise: float
    fonts: list[str]
    plugins: list[str]
    
    def to_dict(self) -> dict:
        return {
            "user_agent": self.user_agent,
            "browser_type": self.browser_type,
            "platform": self.platform,
            "screen_width": self.screen_width,
            "screen_height": self.screen_height,
            "timezone": self.timezone,
            "language": self.language,
            "cpu_cores": self.cpu_cores,
            "device_memory": self.device_memory,
            "color_depth": self.color_depth,
            "webgl_vendor": self.webgl_vendor,
            "webgl_renderer": self.webgl_renderer,
            "canvas_noise": self.canvas_noise,
            "audio_noise": self.audio_noise,
            "fonts": self.fonts,
            "plugins": self.plugins,
        }


class FingerprintGenerator:
    """Generates realistic browser fingerprints."""
    
    def __init__(self, seed: int | None = None):
        self.rng = random.Random(seed)
    
    def generate(self, browser_type: str = "chromium") -> Fingerprint:
        """Generate a consistent fingerprint for a browser type."""
        # Pick a profile
        profile_key = self._pick_profile(browser_type)
        user_agent = self.rng.choice(USER_AGENTS[profile_key])
        
        # Determine platform from profile
        if "windows" in profile_key:
            platform = PLATFORMS["windows"]
        elif "linux" in profile_key:
            platform = PLATFORMS["linux"]
        else:
            platform = PLATFORMS["mac"]
        
        # Screen resolution
        width, height = self.rng.choice(SCREEN_RESOLUTIONS)
        
        # Timezone and language (correlated)
        timezone = self.rng.choice(TIMEZONES)
        language = self.rng.choice(LANGUAGES)
        
        # Hardware
        cpu_cores = self.rng.choice(CPU_CORES)
        device_memory = self.rng.choice(DEVICE_MEMORY)
        color_depth = self.rng.choice(COLOR_DEPTHS)
        
        # WebGL (browser-specific)
        webgl_vendor, webgl_renderer = self._get_webgl(browser_type)
        
        # Noise values (small random values for fingerprinting resistance)
        canvas_noise = self.rng.uniform(0.001, 0.01)
        audio_noise = self.rng.uniform(0.0001, 0.001)
        
        # Fonts and plugins (subset of common ones)
        fonts = self._get_fonts(platform)
        plugins = self._get_plugins(browser_type)
        
        return Fingerprint(
            user_agent=user_agent,
            browser_type=browser_type,
            platform=platform,
            screen_width=width,
            screen_height=height,
            timezone=timezone,
            language=language,
            cpu_cores=cpu_cores,
            device_memory=device_memory,
            color_depth=color_depth,
            webgl_vendor=webgl_vendor,
            webgl_renderer=webgl_renderer,
            canvas_noise=canvas_noise,
            audio_noise=audio_noise,
            fonts=fonts,
            plugins=plugins,
        )
    
    def _pick_profile(self, browser_type: str) -> str:
        """Pick a user agent profile matching browser type."""
        if browser_type == "firefox":
            profiles = [k for k in USER_AGENTS.keys() if "firefox" in k]
        elif browser_type == "webkit":
            profiles = [k for k in USER_AGENTS.keys() if "safari" in k]
        else:  # chromium
            profiles = [k for k in USER_AGENTS.keys() if "chrome" in k or "edge" in k]
        return self.rng.choice(profiles)
    
    def _get_webgl(self, browser_type: str) -> tuple[str, str]:
        """Get WebGL vendor/renderer for browser."""
        if browser_type == "firefox":
            return (
                "Mozilla",
                "Mozilla Firefox"
            )
        elif browser_type == "webkit":
            return (
                "Apple",
                "Apple GPU"
            )
        else:  # chromium
            vendors = [
                ("Google Inc.", "ANGLE (NVIDIA GeForce GTX 1660 Ti Direct3D11 vs_5_0 ps_5_0)"),
                ("Google Inc.", "ANGLE (AMD Radeon RX 5700 XT Direct3D11 vs_5_0 ps_5_0)"),
                ("Google Inc.", "ANGLE (Intel UHD Graphics 630 Direct3D11 vs_5_0 ps_5_0)"),
                ("Google Inc.", "ANGLE (NVIDIA GeForce RTX 3070 Direct3D11 vs_5_0 ps_5_0)"),
            ]
            return self.rng.choice(vendors)
    
    def _get_fonts(self, platform: str) -> list[str]:
        """Get common fonts for platform."""
        base_fonts = [
            "Arial", "Arial Black", "Comic Sans MS", "Courier New",
            "Georgia", "Impact", "Times New Roman", "Trebuchet MS",
            "Verdana", "Webdings", "Wingdings", "Tahoma", "Lucida Console",
        ]
        if "Win" in platform:
            extra = ["Segoe UI", "Calibri", "Cambria", "Consolas", "Candara", "Corbel"]
        elif "Mac" in platform:
            extra = ["Helvetica", "Helvetica Neue", "Avenir", "San Francisco", "Menlo", "Monaco"]
        else:
            extra = ["DejaVu Sans", "Liberation Sans", "Noto Sans", "Ubuntu", "Cantarell"]
        all_fonts = base_fonts + extra
        return self.rng.sample(all_fonts, k=self.rng.randint(12, len(all_fonts)))
    
    def _get_plugins(self, browser_type: str) -> list[str]:
        """Get common plugins for browser."""
        if browser_type == "firefox":
            return [
                "PDF.js", "OpenH264 Video Codec", "Widevine Content Decryption Module"
            ]
        elif browser_type == "webkit":
            return [
                "QuickTime Plug-in", "Java Applet Plug-in", "Silverlight Plug-in"
            ]
        else:  # chromium
            return [
                "Chrome PDF Viewer", "Chrome PDF Viewer", "Native Client",
                "Widevine Content Decryption Module", "QuickTime Plug-in"
            ]


async def apply_fingerprint(page, fingerprint: Fingerprint) -> None:
    """Apply fingerprint to Playwright page via CDP."""
    try:
        client = await page.context.new_cdp_session(page)
        
        # Override user agent
        await client.send("Network.setUserAgentOverride", {
            "userAgent": fingerprint.user_agent,
            "platform": fingerprint.platform,
        })
        
        # Set timezone
        await client.send("Emulation.setTimezoneOverride", {
            "timezoneId": fingerprint.timezone,
        })
        
        # Set locale/language
        await client.send("Emulation.setLocaleOverride", {
            "locale": fingerprint.language.split(",")[0],
        })
        
        # Set screen size
        await client.send("Emulation.setDeviceMetricsOverride", {
            "width": fingerprint.screen_width,
            "height": fingerprint.screen_height,
            "deviceScaleFactor": 1,
            "mobile": False,
            "screenWidth": fingerprint.screen_width,
            "screenHeight": fingerprint.screen_height,
            "positionX": 0,
            "positionY": 0,
            "dontSetVisibleSize": False,
        })
        
        # Inject fingerprint into page context
        await page.add_init_script(f"""
            // Override navigator properties
            Object.defineProperty(navigator, 'platform', {{
                get: () => '{fingerprint.platform}',
            }});
            Object.defineProperty(navigator, 'hardwareConcurrency', {{
                get: () => {fingerprint.cpu_cores},
            }});
            Object.defineProperty(navigator, 'deviceMemory', {{
                get: () => {fingerprint.device_memory},
            }});
            Object.defineProperty(navigator, 'language', {{
                get: () => '{fingerprint.language.split(",")[0]}',
            }});
            Object.defineProperty(navigator, 'languages', {{
                get: () => ['{fingerprint.language.split(",")[0]}', '{fingerprint.language.split(",")[1] if "," in fingerprint.language else "en"}'],
            }});
            
            // Screen
            Object.defineProperty(screen, 'width', {{
                get: () => {fingerprint.screen_width},
            }});
            Object.defineProperty(screen, 'height', {{
                get: () => {fingerprint.screen_height},
            }});
            Object.defineProperty(screen, 'colorDepth', {{
                get: () => {fingerprint.color_depth},
            }});
            Object.defineProperty(screen, 'pixelDepth', {{
                get: () => {fingerprint.color_depth},
            }});
            
            // WebGL
            const getParameter = WebGLRenderingContext.prototype.getParameter;
            WebGLRenderingContext.prototype.getParameter = function(parameter) {{
                if (parameter === 37445) return '{fingerprint.webgl_vendor}';
                if (parameter === 37446) return '{fingerprint.webgl_renderer}';
                return getParameter.apply(this, arguments);
            }};
            
            // Canvas noise
            const toDataURL = HTMLCanvasElement.prototype.toDataURL;
            HTMLCanvasElement.prototype.toDataURL = function() {{
                const ctx = this.getContext('2d');
                if (ctx) {{
                    const noise = {fingerprint.canvas_noise};
                    const imageData = ctx.getImageData(0, 0, this.width, this.height);
                    for (let i = 0; i < imageData.data.length; i += 4) {{
                        imageData.data[i] += Math.random() * noise * 255;
                        imageData.data[i+1] += Math.random() * noise * 255;
                        imageData.data[i+2] += Math.random() * noise * 255;
                    }}
                    ctx.putImageData(imageData, 0, 0);
                }}
                return toDataURL.apply(this, arguments);
            }};
            
            // Audio noise
            const audioContext = window.AudioContext || window.webkitAudioContext;
            if (audioContext) {{
                const createAnalyser = audioContext.prototype.createAnalyser;
                audioContext.prototype.createAnalyser = function() {{
                    const analyser = createAnalyser.apply(this, arguments);
                    const getFloatFrequencyData = analyser.getFloatFrequencyData;
                    analyser.getFloatFrequencyData = function(array) {{
                        getFloatFrequencyData.apply(this, arguments);
                        for (let i = 0; i < array.length; i++) {{
                            array[i] += (Math.random() - 0.5) * {fingerprint.audio_noise * 2};
                        }}
                    }};
                    return analyser;
                }};
            }}
        """)
        
        await client.detach()
        
    except Exception as e:
        # CDP might not be available in all contexts
        pass


class FingerprintRotator:
    """Manages fingerprint rotation across pages."""
    
    def __init__(self, seed: int | None = None):
        self.generator = FingerprintGenerator(seed)
        self._current: dict[str, Fingerprint] = {}
    
    def get_fingerprint(self, browser_type: str = "chromium", session_id: str | None = None) -> Fingerprint:
        """Get fingerprint for browser type, optionally tied to session."""
        if session_id and session_id in self._current:
            return self._current[session_id]
        
        fp = self.generator.generate(browser_type)
        if session_id:
            self._current[session_id] = fp
        return fp
    
    def rotate(self, session_id: str, browser_type: str = "chromium") -> Fingerprint:
        """Force rotate fingerprint for session."""
        fp = self.generator.generate(browser_type)
        self._current[session_id] = fp
        return fp
    
    def clear_session(self, session_id: str):
        """Clear fingerprint for session."""
        self._current.pop(session_id, None)


# Global rotator
fingerprint_rotator = FingerprintRotator()