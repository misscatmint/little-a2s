from little_a2s.events import (
    VAC,
    ClientEventChallenge,
    ClientEventGoldsourceInfo,
    ClientEventInfo,
    ClientEventPlayers,
    ClientEventRules,
    Environment,
    ExtraInfo,
    GoldsourceMod,
    GoldsourceModDLL,
    GoldsourceModType,
    Player,
    ServerType,
    Visibility,
)
from little_a2s.reader import Reader
from tests.constants import (
    A2S_INFO_ARMA3,
    A2S_INFO_COUNTERSTRIKE_SOURCE,
    A2S_INFO_GOLDSOURCE_COUNTERSTRIKE,
    A2S_INFO_PROJECT_ZOMBOID,
    A2S_INFO_SIN1_MP,
    A2S_PLAYER,
    A2S_PLAYER_EMPTY,
    A2S_PLAYER_MALFORMED_UTF8,
    A2S_PLAYER_ZERO_PADDED,
    A2S_RULES_ARMA3,
    A2S_RULES_PROJECT_ZOMBOID,
    S2C_CHALLENGE,
)


def test_a2s_info_counterstrike_source() -> None:
    info = ClientEventInfo.from_reader(Reader(A2S_INFO_COUNTERSTRIKE_SOURCE[5:]))
    assert info == ClientEventInfo(
        protocol=2,
        name="game2xs.com Counter-Strike Source #1",
        map="de_dust",
        folder="cstrike",
        game="Counter-Strike: Source",
        id=240,
        players=5,
        max_players=16,
        bots=4,
        type=ServerType.DEDICATED,
        environment=Environment.LINUX,
        visibility=Visibility.PUBLIC,
        vac=VAC.INSECURE,
        version="1.0.0.22",
        extra=None,
    )


def test_a2s_info_sin1_mp() -> None:
    info = ClientEventInfo.from_reader(Reader(A2S_INFO_SIN1_MP[5:]))
    assert info == ClientEventInfo(
        protocol=47,
        name="Sensemann SiN DM",
        map="paradox",
        folder="SiN 1",
        game="SiN 1",
        id=1309,
        players=0,
        max_players=16,
        bots=0,
        type=ServerType.LISTEN,
        environment=Environment.WINDOWS,
        visibility=Visibility.PUBLIC,
        vac=VAC.INSECURE,
        version="1.0.0.0",
        extra=None,
    )


def test_a2s_info_project_zomboid() -> None:
    info = ClientEventInfo.from_reader(Reader(A2S_INFO_PROJECT_ZOMBOID[5:]))
    assert info == ClientEventInfo(
        protocol=17,
        name="play.thegamecracks.xyz",
        map="Muldraugh, KY",
        folder="zomboid",
        game="Project Zomboid",
        id=0,
        players=0,
        max_players=8,
        bots=0,
        type=ServerType.DEDICATED,
        environment=Environment.LINUX,
        visibility=Visibility.PRIVATE,
        vac=VAC.SECURE,
        version="1.0.0.0",
        extra=ExtraInfo(
            port=16261,
            steam_id=90276363418906655,
            spectator_port=None,
            spectator_name=None,
            keywords="",
            game_id=108600,
        ),
    )


def test_a2s_info_arma3() -> None:
    info = ClientEventInfo.from_reader(Reader(A2S_INFO_ARMA3[5:]))
    assert info == ClientEventInfo(
        protocol=17,
        name="Warriors Haven Invade & Annex | discord.gg/9uNHvhvJVB",
        map="Enoch",
        folder="Arma3",
        game="Warriors Haven Framework (Livonia)",
        id=0,
        players=0,
        max_players=40,
        bots=0,
        type=ServerType.DEDICATED,
        environment=Environment.WINDOWS,
        visibility=Visibility.PUBLIC,
        vac=VAC.INSECURE,
        version="2.20.153368",
        extra=ExtraInfo(
            port=2306,
            steam_id=90276534468495365,
            spectator_port=None,
            spectator_name=None,
            keywords="bt,r220,n152946,s7,i3,mf,lf,vt,dt,tcoop,g65545,hd1e806d5,f1,c-2147483648--2147483648,pw,e15,j0,k0,",
            game_id=107410,
        ),
    )


def test_a2s_info_app_id() -> None:
    # Games with IDs above 16 bits send 0 as the ID and the real one in the game ID.
    assert (
        ClientEventInfo.from_reader(Reader(A2S_INFO_PROJECT_ZOMBOID[5:])).app_id
        == 108600
    )
    assert ClientEventInfo.from_reader(Reader(A2S_INFO_ARMA3[5:])).app_id == 107410
    # Without a game ID, the 16-bit ID is used.
    assert (
        ClientEventInfo.from_reader(Reader(A2S_INFO_COUNTERSTRIKE_SOURCE[5:])).app_id
        == 240
    )


def test_a2s_info_goldsource() -> None:
    info = ClientEventGoldsourceInfo.from_reader(
        Reader(A2S_INFO_GOLDSOURCE_COUNTERSTRIKE[5:])
    )
    assert info == ClientEventGoldsourceInfo(
        address="77.111.194.110:27015",
        name="FR - VeryGames.net - Deatmatch - only surf_ski - ngR",
        map="surf_ski",
        folder="cstrike",
        game="Counter-Strike",
        players=12,
        max_players=18,
        protocol=47,
        type=ServerType.DEDICATED,
        environment=Environment.LINUX,
        visibility=Visibility.PUBLIC,
        mod=GoldsourceMod(
            link="www.counter-strike.net",
            download_link="",
            version=1,
            size=184000000,
            type=GoldsourceModType.SINGLE_AND_MULTIPLAYER,
            dll=GoldsourceModDLL.EXTENSION,
        ),
        vac=VAC.SECURE,
        bots=0,
    )


def test_a2s_player() -> None:
    players = ClientEventPlayers.from_reader(Reader(A2S_PLAYER[5:]))
    assert players == ClientEventPlayers(
        players=[
            Player(
                index=1,
                name="[D]---->T.N.W<----",
                score=14,
                duration=514.370361328125,
            ),
            Player(
                index=2,
                name="Killer !!!",
                score=5,
                duration=434.2844543457031,
            ),
        ]
    )


def test_a2s_player_empty() -> None:
    players = ClientEventPlayers.from_reader(Reader(A2S_PLAYER_EMPTY[5:]))
    assert players == ClientEventPlayers(players=[])


def test_a2s_player_zero_padded() -> None:
    players = ClientEventPlayers.from_reader(Reader(A2S_PLAYER_ZERO_PADDED[5:]))
    assert len(players) == 89
    assert players[0] == Player(index=0, name="playe", score=0, duration=58906.79296875)
    assert players[-1] == Player(index=0, name="player", score=0, duration=0.0)


def test_a2s_player_fewer_than_count() -> None:
    data = b"\x03" + A2S_PLAYER[6:]
    players = ClientEventPlayers.from_reader(Reader(data))
    assert players == ClientEventPlayers.from_reader(Reader(A2S_PLAYER[5:]))


def test_a2s_player_malformed_utf8() -> None:
    players = ClientEventPlayers.from_reader(Reader(A2S_PLAYER_MALFORMED_UTF8[5:]))
    assert players == ClientEventPlayers(
        players=[
            Player(
                index=0,
                name="芭芭�?",
                score=0,
                duration=619.0714111328125,
            ),
        ]
    )


def test_a2s_rules_project_zomboid() -> None:
    rules = ClientEventRules.from_reader(Reader(A2S_RULES_PROJECT_ZOMBOID[5:]))
    assert rules == ClientEventRules(
        rules={
            b"description": b"",
            b"modCount": b"304",
            b"mods": b"CasterPlus;TombBodyCompat;TombBody;TombBodyCustom;TombBodyTex;TombBodyTexDOLL;TombBodyTexNUDE;velkiel_fixed_cooking_recipes",
            b"open": b"0",
            b"public": b"1",
            b"pvp": b"1",
            b"version": b"41.78.16",
        }
    )


def test_a2s_rules_arma3() -> None:
    rules = ClientEventRules.from_reader(Reader(A2S_RULES_ARMA3[5:]))
    assert rules == ClientEventRules(
        rules={
            b"\x01\x1a": b'\x03\x08\x01\x03\x1b\x9b\x01\x02ba3\xf6\x85\x9f\x0e\x14~>\xc3a\xf8>v;<\xe1^\x12\x15Q3\x7f\xec\x01\x03}\x10\xf5\xaa\xd6\xaad\xd0PQ\x16\x03"n/\x90(\xb4\x90\xad\xceE#\xfa\xac\xa8\xd6\x13\x12\xa7\x19\x01\x026M\x0e\xf6\x13\xd0f(\x01\x02_\xfc\xe8$\x13\x16g(\x01\x02\x1c\x9f\xcc\x05\x04q\x11\x94\xa6\x15Advanced Vault System\xb7K\\4\x04b\xfe\x07',
            b"\x02\x1a": b"\x83\x13Alternative Running\xf1G\xef\xc4\x04z\xdb\xd4z\x0f@Arsenal Search\xdf\xc9f#\x04/\x02\xec\xb7\x1cAutomatic Warning Suppressor\xba\xc00\xa9\x04Una\xa6\x10Better Inventory\x1d\x15\x8b\xeb\x04\xa0Y\xef{\r@Blurry",
            b"\x03\x1a": b" Laser\xa8\x84h!\x04\x15\xe4\xde\x1a\x1dCommunity Base Addons v3.18.4A\xbd*a\x04\xeb\xbc\xee1\x11@CH View Distance\xae\x05Q\xea\x04(Nl\xb2\x17Dying and Hit Reactions\xf3\xab-\xbf\x04\xc6\xce\xc6\xcc\x17@Drongos Gre",
            b"\x04\x1a": b"nade Tweaks\x8d\xd2\x0e\xe4\x04\xf7\x830\xb6\x0eE22: Northstar\xac#\xa10\x04\x0e\xb4\xd2\xa7\x19E22: Russian Armed ForcesS\xcf4\xc1\x04\x89\xc7\xef(\x0cEden Objects\x8b\x03\xc6\x11\x04M\xec\xf9\xcf'Expanded Actions and Vehi",
            b"\x05\x1a": b"cle Animations\x0e\xce\xe6\xcf\x04Apv\xc7\x14Hide Among The Grass\xc6@Z\xdc\x04}(\xae\xc6\x16JCA - Infantry Arsenals\x94\x9d\x90\x04\xfc\xa0\x07\xcf\x18JCA - Infantry Equipmentlc[\x1e\x04\x96\xd4\xbe\xb4\x17JCA - Q",
            b"\x06\x1a": b'OL Essentials V2\xe8\x95\x15)\x04\xd7\x9e\x8e\xae\x1cJCA - SPAR Retexture ProjectJ\xe3\xba\xad\x04$\x81!\xcb*JSRS Soundmod 2025 Beta - AiO Compat Files\x05\xcd%g\x04\x0c*!\xcb"JSRS Soundm',
            b"\x07\x1a": b"od 2025 Beta RC3 - Beta\x93\x03H\xe0\x04\xa0\xb0\xfc\xb0\x18@Ladder Tweak Remastered\x82\xab\xd4\x0c\x04\xde\x1a\x84i\x19No More Aircraft BouncingnZNc\x04\x06\x9bG\xa7\x14WebKnights Footstepsw\xd2\x08\xf4\x04",
            b"\x08\x1a": b";\x15\xee~\x17SFX Project: Remasteredvc\xe7{\x04L>Ro\x10Pylon Manager V4\x8d\xbd\xc0\x82\x042J\xa6\xcd\x14@Reload While Aiming\xe7\x81\x92\xb2\x04\xf2mA*\x15@SSD Death Screams 21\x82\xb7F\xfa\x04J\xd4\xa1\xd5\x15UH",
            b"\t\x1a": b"-80 Ghost Hawk Plus4+\xbf|\x04\x01\x01\x7f\xd8\x80\x18Vehicle Inventory System\xc8B\xec;\x04\x16\x05\xbd\xba\x10WBK Simple Blood\x99\xa59+\x04\xe5\xa3\xeaj\x17White Phosphor - No ACE\xa8\x1916aa-3lsr-20",
            b"\n\x1a": b"20-01-01.7af9\x052600K\x0c3den_Objects\x02a3\x08A3RO_1.1\x04A3TI\x0bA3TI_REAPIR\x12AdvancedRappelling\x0eAdvancedTowing\x17AdvancedUrbanRappelling\x03AGE\rAlk",
            b"\x0b\x1a": b"SwimFaster\x03ALP\x03ANZ\nASBE_1.1.1\x1cAutomatic-Warning-Suppressor\tbadbenson\x10better_Inventory\x0cBloodwynBWLH\x07Bromine\nCasper_TFG\x11cba_3.18.",
            b"\x0c\x1a": b"4.250711\x14CCA_1.0.1.0-11cad8fc\x02CH\x07Cryptid\x04csla\x18cup_terrains_core-1.17.1\x10cup_units-1.18.1\x13cup_vehicles-1.18.1\x12cup_weapons-1.18.1\x03",
            b"\r\x1a": b"CZB\x04dbag\x0eDetected_error\x0cdirt_0.4.0.0\tDITC_2025\x13diwako_dui_1.12.2.0\x0cdrakovac_154\x14drongosgrenadetweaks\x0bDVK_ALTCSAT\x04dyel\x07DrunkeN\x02e",
            b"\x0e\x1a": b"f\x0bEnhancedGPS\x0bEnhancedMap\x1dEnhancedSoundscape_2020_01_05\tenh_8.7.1\x0bEricJAddons\x0eEscalation2022\x07f35_hnt\x18Fat_Lurch_TurretEnhanced\rF",
            b"\x0f\x1a": b"at_Lurch_VIS\x1fFat_Lurch_White_Phosphor_No_ACE\tFA_EMB312\x03fhs\x03FVL\x03GAC\x04GanX\x05GENIX\nGF_ReColor\x05globe\x02gm\tGX_DRONES\x19hatchet_interaction",
            b"\x10\x1a": b"_0.3.1\x0cibr_regero11\tibr_yul11\x03icm\x07iskyefx\x0ciskyStocatto\x08ISKY_EFX\rJAMReconHoods\x05Jason\x07JFXAMv2\x10JointCom_Armoury\x10JointCom_Armoury\x07J",
            b"\x11\x1a": b"SDFmod\x14jsrs_2025_aio_comapt\x0ejsrs_2025_main\x0fjsrs_extra_2020\x15jsrs_soundmod_2020_v2\x04juju\x05Kaska\x15KJW_TwoPrimaryWeapons\x0cLalaPeralv01\x0f",
            b"\x12\x1a": b"lambs_2.6.1.502\rlambs_2.6.2.1\tlambs_mod\x06larisa\rLeopard20.ADT\x0clot_aaf_scar\x0flxrf_cba_compat\x0flxws_cba_compat\tmagRepack\tMaxjoiner\tM",
            b"\x13\x1a": b"ax_Women\x07MBG_AGB\x0cmehland_v120\x03MHS\x12Modern_Pistol_Pack\x16Modules_f_JoeLiScripts\x03MSS\x08MTK_Mods\x0cNemo_VOEREX4\x06NIArms\tNightFury\x16NoMoreAi",
            b"\x14\x1a": b"rcraftBouncing\x03pdb\x08pdt_envg\x0cPeralAH1Zv01\x0bPeralF16v01\x06POLPOX\x1cPOLPOX_LadderTweakRemastered\x19POLPOX_MapToolsRemastered\x03qav\x07r0dx864\x02",
            b"\x15\x1a": b"rf\x0fRKSLStudios2019\x03Ruf\x05Ruizu\tRUOP_V110\x0bruPal_mpkey\x12secondary_gl_1.1.0\nSecondWind\rSFX_R_Project\x08sil_hatg\x08Simcardo\x08SMA2.7.1\x06SNMod",
            b"\x16\x1a": b"s\x06SNMods\x06SNMods\x03spe\nSpearpoint\x12sps_ai_axmc_v1_4_1\x0cStaticRadios\rtacs_2.4.0.55\nTCGM_Girls\x0eTCGM_Girls1.55\x10TCGM_Multi-Girls\x03TEC\x04TF4",
            b"\x17\x1a": b"7\x10uh80_tgp_1.0.0.0\x14UK3CB_BAF_Weapon_3_1\x13UMB_Colombia_v0.9.5\nUnderSiege\x06Uriki9\x14USAF_AC130_BETA_V1.2\x14usaf_fighter-1.0.6.2\x11usaf_ma",
            b"\x18\x1a": b"in-1.0.6.2\x14usaf_utility-1.0.6.2\x0bV12BIKEPACK\x08vagineer\x08Variable\x02vd\x02vn\x06VSMAOQ\x16WarriorsHaven_AlexLyon\x1cWBK_AlternativeRunningv3Keys\x0b",
            b"\x19\x1a": b"WBK_AVS_Key\x0cWBK_BloodMod\x0fWBK_DeathAndHit\x10WBK_FootstepsKey\x0bWBK_TMW_Key\x02ws\x13ww2_spex_2025_07_22\x06xakuda\x03zab\x04Zabb\rZEI-Continued\rzen_",
            b"\x1a\x1a": b"1.15.1.36",
        }
    )


def test_s2c_challenge() -> None:
    challenge = ClientEventChallenge.from_reader(Reader(S2C_CHALLENGE[5:]))
    assert challenge == ClientEventChallenge(challenge=584425803)
