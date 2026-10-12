# Example Prompts for Auto Deal Searcher

## DJI Drone (from auto.yaml)
```yaml
prompt: |
  I want a DJI drone for under €350 with a 3-axis gimbal, all-around obstacle sensors,
  at least 20 minutes flight time. Prefer DJI Mini 3 Pro, Air 2S, or Mavic 3 Classic.
  Condition: refurbished or open-box acceptable. Sites: BackMarket, Alza (open-box), eBay, Bazos.
  Category: electronics. Exclude: broken, for parts, no controller.
```

## Gaming Laptop
```yaml
prompt: |
  Looking for a gaming laptop under €1000 with RTX 3060 or better, 16GB RAM, 1TB SSD.
  15.6" screen, 144Hz+. Condition: new or open-box. Sites: Alza, eBay, Amazon.
  Category: electronics. Exclude: refurbished with cosmetic damage.
```

## Used Car Parts
```yaml
prompt: |
  Need brake discs and pads for 2018 Volkswagen Golf VII 1.5 TSI.
  OEM or quality aftermarket (Brembo, Textar, ATE). Condition: new only.
  Sites: Autobazar, eBay, TME. Category: auto.
```

## Refurbished iPhone
```yaml
prompt: |
  iPhone 13 or 14, 128GB+, any color. Under €600. Condition: refurbished (BackMarket grade A/B) or open-box.
  Sites: BackMarket, Alza, eBay. Category: electronics. Must have 12+ month warranty.
```

## Coffee Machine
```yaml
prompt: |
  DeLonghi or Jura automatic coffee machine, under €400. Bean-to-cup, milk frother.
  Condition: new or open-box. Sites: Alza, Bazos, eBay. Category: appliances.
```

## Monitor
```yaml
prompt: |
  27" 1440p 144Hz+ IPS monitor for gaming/work. Under €300. G-Sync/FreeSync compatible.
  Condition: new or open-box. Sites: Alza, eBay, Amazon, Techfun. Category: electronics.
```

## Usage
```bash
# Single run with prompt file
python -m src.cli run --prompt-file prompts/auto.yaml

# Single run with inline prompt
python -m src.cli run --prompt "DJI drone under 350 euros" --condition refurbished --category electronics

# Install scheduled tasks (runs at configured times)
python -m src.cli schedule-install
```