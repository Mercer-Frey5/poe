from agents.dual_output import DualOutput, VisualPayload


def test_verbal_only_response():
    out = DualOutput(verbal="Ciao, Signore.")
    assert out.verbal == "Ciao, Signore."
    assert out.visual is None


def test_response_with_visual_payload():
    out = DualOutput(
        verbal="Ecco il report.",
        visual=VisualPayload(type="osint_report", data={"nome": "Mario Rossi"}),
    )
    assert out.visual.type == "osint_report"
    assert out.visual.data["nome"] == "Mario Rossi"
    assert out.visual.template is None
