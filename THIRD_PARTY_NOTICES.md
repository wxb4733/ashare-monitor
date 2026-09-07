# 第三方声明

本项目借鉴/集成了以下开源项目的代码与思路：

## OpenBB（Open Data Platform）

- 仓库：https://github.com/OpenBB-finance/OpenBB
- 官网：https://openbb.co
- 许可证：AGPLv3 License
- 版权：Copyright (c) OpenBB Inc.
- 集成方式：作为**可选依赖**（`pip install -e ".[openbb]"`）的 Python 数据聚合层
  运行，经其统一路由（`from openbb import obb`）拉取全球资产/宏观数据，
  用于美股/加密货币/全球宏观等本地数据源未覆盖的市场。
- 使用注意：
  - 本项目的私有仓库**不修改、不分发 OpenBB 源码**，仅以依赖形式调用其
    Python API，故不触发 AGPLv3 的分发传染义务；
  - 若未来将本项目的衍生修改版本对外分发，需按 AGPLv3 开源对应修改。
- AGPLv3 全文见 https://www.gnu.org/licenses/agpl-3.0.html

## easyquotation

- 仓库：https://github.com/shidenggui/easyquotation
- 许可证：MIT License
- 版权：Copyright (c) 2018 shidenggui
- 借鉴内容：新浪（`hq.sinajs.cn`）与腾讯（`qt.gtimg.cn`）免费行情接口的
  报文解析逻辑、证券代码市场前缀判断规则，
  见 `src/ashare_monitor/providers/sina.py`、`tencent.py`、`base.py`。

MIT License 全文：

```
MIT License

Copyright (c) 2018 shidenggui

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
