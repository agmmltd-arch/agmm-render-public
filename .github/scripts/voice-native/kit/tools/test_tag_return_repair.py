import format_engine as engine

def test_unsupported_hero_return_replans_without_skipping_gates():
    issue='the hero tag returns on beat s01 where the figure is not spoken (it may return only on the beats where the voice says it)'
    assert [flag for flag,_ in engine.repair_flags([issue],set())]==['tag_zero']
    assert engine.repair_flags([issue],{'tag_zero'})==[]
    assert engine.repair_flags(['object content repeated: ungrounded repeat'],set())==[]

if __name__=='__main__':test_unsupported_hero_return_replans_without_skipping_gates();print('hero-return repair: PASS')
