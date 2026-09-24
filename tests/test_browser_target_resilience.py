import unittest

from browser.queue_runner import _live_page
from learning.review_capture import ReviewCapture


class _FakePage:
    def __init__(self, url="https://example.test", closed=False, frames=None):
        self.url = url
        self._closed = closed
        self.frames = list(frames or [])

    def is_closed(self):
        return self._closed


class _FakeContext:
    def __init__(self, pages):
        self.pages = list(pages)


class _DisappearingLocator:
    def count(self):
        raise RuntimeError("Target page, context or browser has been closed")


class _FrameWithDisappearingControls:
    def locator(self, _selector):
        return _DisappearingLocator()


class BrowserTargetResilienceTests(unittest.TestCase):
    def test_live_page_falls_back_when_preferred_was_closed(self):
        stale = _FakePage("https://old.test", closed=True)
        live = _FakePage("https://new.test", closed=False)
        context = _FakeContext([stale, live])

        self.assertIs(_live_page(context, preferred=stale), live)

    def test_live_page_prefers_requested_active_url(self):
        first = _FakePage("https://first.test", closed=False)
        active = _FakePage("https://active.test", closed=False)
        context = _FakeContext([first, active])

        self.assertIs(
            _live_page(context, preferred=first, active_url="https://active.test"),
            active,
        )

    def test_review_capture_returns_empty_for_closed_page(self):
        page = _FakePage(closed=True)
        self.assertEqual(ReviewCapture().capture(page), {})

    def test_review_capture_survives_target_closing_during_locator_count(self):
        page = _FakePage(frames=[_FrameWithDisappearingControls()])
        self.assertEqual(ReviewCapture().capture(page), {})


if __name__ == "__main__":
    unittest.main()
