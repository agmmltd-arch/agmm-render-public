import format_engine as engine

def test_unsupported_hero_return_replans_without_skipping_gates():
    issue='the hero tag returns on beat s01 where the figure is not spoken (it may return only on the beats where the voice says it)'
    assert [flag for flag,_ in engine.repair_flags([issue],set())]==['tag_zero']
    assert engine.repair_flags([issue],{'tag_zero'})==[]
    assert engine.repair_flags(['object content repeated: ungrounded repeat'],set())==[]

def test_first_body_group_is_not_frame_zero():
    story,words=engine.make_fixture()
    plan=engine.new_plan('ZZ1',story,words,'dossier','D3')
    plan.wins[1].object={'kind':'price_tag','content':{}}
    plan.flags={'tag_zero'}
    first=engine.plan_states(plan)['groups'][0]
    assert first['object'] is None and first.get('bare') is True
    story,words=engine.make_fixture();story['huge_cost']['spoken']=[10,11]
    plan=engine.new_plan('ZZ1',story,words,'dossier','D3')
    plan.wins[1].object={'kind':'price_tag','content':{}}
    plan.flags={'tag_zero'}
    assert engine.plan_states(plan)['groups'][0]['object']['kind']=='price_tag'

if __name__=='__main__':
    test_unsupported_hero_return_replans_without_skipping_gates();test_first_body_group_is_not_frame_zero();print('hero-return repair: PASS')
