"""
轉場模組。

新增自訂轉場：
  1. 定義一個 function(clips: list) -> list，修改 clips 後回傳
  2. 加入 TRANSITION_REGISTRY
  3. 在 base_config.yaml 修改 transition 為新 key
"""
from moviepy import vfx


def _hard_cut(clips: list) -> list:
    """直接切換，無任何過渡效果。"""
    return clips


def _fade_black(clips: list, duration: float = 0.3) -> list:
    """每個 clip 淡出至黑，下一個 clip 從黑淡入。"""
    result = []
    for i, clip in enumerate(clips):
        c = clip.with_effects([vfx.FadeOut(duration)])
        if i > 0:
            c = c.with_effects([vfx.FadeIn(duration)])
        result.append(c)
    return result


def _crossfade(clips: list, duration: float = 0.4) -> list:
    """
    交叉溶解：每個場景結尾淡出，下一個場景開頭淡入（視覺交疊）。
    比 fade_black 更流暢，適合敘事型短影音。
    """
    result = []
    for i, clip in enumerate(clips):
        effects = []
        if i > 0:
            effects.append(vfx.CrossFadeIn(duration))
        if i < len(clips) - 1:
            effects.append(vfx.CrossFadeOut(duration))
        result.append(clip.with_effects(effects) if effects else clip)
    return result


TRANSITION_REGISTRY = {
    "hard_cut":   lambda clips: _hard_cut(clips),
    "fade_black": lambda clips: _fade_black(clips, duration=0.3),
    "crossfade":  lambda clips: _crossfade(clips, duration=0.4),
}
