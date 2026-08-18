# 第三方声明

本项目借鉴了以下开源项目的代码与思路：

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
