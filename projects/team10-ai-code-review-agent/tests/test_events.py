import unittest

from backend.app.services.events import InMemoryReviewEventBus


class ReviewEventBusTest(unittest.IsolatedAsyncioTestCase):
    async def test_stream_returns_sse_events_until_terminal_event(self):
        bus = InMemoryReviewEventBus()
        bus.publish("run-1", "review_queued", {"repository": "team/repo"})
        bus.publish("run-1", "review_completed", {"findings_count": 1})

        chunks = []
        async for chunk in bus.stream("run-1"):
            chunks.append(chunk)

        self.assertEqual(len(chunks), 2)
        self.assertIn("event: review_queued", chunks[0])
        self.assertIn("event: review_completed", chunks[1])
        self.assertIn('"review_run_id": "run-1"', chunks[1])


if __name__ == "__main__":
    unittest.main()
