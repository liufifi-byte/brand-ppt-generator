#!/usr/bin/env python3
"""svg → pptx 转换入口 (vendored svg_to_pptx 包的薄封装)。

用法: python run_converter.py <work_dir> -s svg -o out.pptx -f ppt169 -q
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from svg_to_pptx import main

if __name__ == "__main__":
    main()
