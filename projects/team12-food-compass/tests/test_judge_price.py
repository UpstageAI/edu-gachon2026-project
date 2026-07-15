from app.tools.judge import judge_price, parse_price


class TestParsePrice:
    def test_comma_string(self):
        assert parse_price("3,606") == 3606.0

    def test_missing_dash(self):
        assert parse_price("-") is None

    def test_empty_string(self):
        assert parse_price("") is None

    def test_plain_number(self):
        assert parse_price("1200") == 1200.0

    def test_whitespace_dash(self):
        assert parse_price(" - ") is None


class TestJudgePrice:
    def test_expensive(self):
        # 상추: 1주일 전 4500 vs 1개월 전 2800 → +60.7% → 비쌈
        result = judge_price(dpr1="-", dpr7="-", dpr3="4,500", dpr5="2,800")
        assert result.status == "비쌈"
        assert result.diff_pct > 10

    def test_expensive_small_margin(self):
        # 당근: 1주일 전 3,600 vs 1개월 전 3,100 → +16.13% → 비쌈 (10% 임계값 기준)
        result = judge_price(dpr1="-", dpr7="-", dpr3="3,600", dpr5="3,100")
        assert result.status == "비쌈"
        assert result.diff_pct > 10

    def test_appropriate_minus(self):
        # 무: 1주일 전 2,000 vs 1개월 전 2,050 → -2.4% → 적정
        result = judge_price(dpr1="-", dpr7="-", dpr3="2,000", dpr5="2,050")
        assert result.status == "적정"
        assert -10 <= result.diff_pct <= 10

    def test_appropriate_positive(self):
        # 감자: 1주일 전 2,050 vs 1개월 전 2,000 → +2.5% → 적정
        result = judge_price(dpr1="-", dpr7="-", dpr3="2,050", dpr5="2,000")
        assert result.status == "적정"
        assert -10 <= result.diff_pct <= 10

    def test_cheap(self):
        # 오이: 1주일 전 1200 vs 1개월 전 1400 → -14.3% → 쌈
        result = judge_price(dpr1="-", dpr7="-", dpr3="1,200", dpr5="1,400")
        assert result.status == "쌈"
        assert result.diff_pct < -10

    def test_cheap_small_margin(self):
        # 배추: 1주일 전 1,900 vs 1개월 전 2,300 → -17.39% → 쌈 (10% 임계값 기준)
        result = judge_price(dpr1="-", dpr7="-", dpr3="1,900", dpr5="2,300")
        assert result.status == "쌈"
        assert result.diff_pct < -10

    def test_missing_dpr3(self):
        # 깻잎: 1주일 전 가격 결측 → 적정 + diff_pct=0.0
        result = judge_price(dpr1="-", dpr7="-", dpr3="-", dpr5="1,600")
        assert result.status == "적정"
        assert result.diff_pct == 0.0

    def test_missing_dpr5(self):
        # 1개월 전 가격 결측 → 적정 + diff_pct=0.0
        result = judge_price(dpr1="-", dpr7="-", dpr3="4,500", dpr5="-")
        assert result.status == "적정"
        assert result.diff_pct == 0.0