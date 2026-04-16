#!/usr/bin/env python3
"""知乎盐选小说下载器 - 主入口"""

import sys
import logging
from cli import main


if __name__ == '__main__':
    # 配置日志
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # 运行CLI
    main()
