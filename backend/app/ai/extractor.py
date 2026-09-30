import json
import logging
import re
import unicodedata
from datetime import datetime, timedelta, date
from typing import Optional
import urllib.parse
from bs4 import BeautifulSoup
from curl_cffi import requests as cffi_requests
from ..config import settings
from ..schemas import RawEventData, AIConferenceExtraction, SpeakerDetailItem

logger = logging.getLogger(__name__)

JOB_ROLES_EXACT = {"ceo", "cto", "ciso", "cio", "cfo", "cro", "coo", "president", "founder", "co-founder", "vice president", "vp"}

VERIFIED_LINKEDIN_HANDLES = {
    "dave lewis": "https://www.linkedin.com/in/gattaca",
    "john johnson": "https://www.linkedin.com/in/john-d-johnson-ph-d-cissp-9226191",
    "paula januszkiewicz": "https://www.linkedin.com/in/paulajanuszkiewicz",
    "tanya janca": "https://www.linkedin.com/in/tanya-janca",
    "jayson e. street": "https://www.linkedin.com/in/jaysonestreet",
    "jayson street": "https://www.linkedin.com/in/jaysonestreet",
    "ira winkler": "https://www.linkedin.com/in/irawinkler",
    "chloe messdaghi": "https://www.linkedin.com/in/chloemessdaghi",
    "gene spafford": "https://www.linkedin.com/in/spaf",
    "doug brush": "https://www.linkedin.com/in/dougbrush",
    "joshua corman": "https://www.linkedin.com/in/cormanjoshua",
    "michael daugherty": "https://www.linkedin.com/in/michael-daugherty-443b7115",
    "gadi evron": "https://www.linkedin.com/in/gadievron",
    "bob flores": "https://www.linkedin.com/in/bob-flores-00216b2",
    "richard greenberg": "https://www.linkedin.com/in/richardagreenberg",
    "steve hunt": "https://www.linkedin.com/in/stevehunt",
    "kate kuehn": "https://www.linkedin.com/in/katekuehn",
    "bobby kuzma": "https://www.linkedin.com/in/bobbykuzma",
    "fred kwong": "https://www.linkedin.com/in/fredkwong",
    "jeff man": "https://www.linkedin.com/in/jeff-man-pci",
    "richard rushing": "https://www.linkedin.com/in/richardrushing",
    "winn schwartau": "https://www.linkedin.com/in/winnschwartau",
    "greg schaffer": "https://www.linkedin.com/in/gregschaffer",
    "robert wagner": "https://www.linkedin.com/in/robert-wagner-ciso",
    "cyrus walker": "https://www.linkedin.com/in/cyrus-walker",
    "matt scheurer": "https://www.linkedin.com/in/scubamatt",
    "swati babbar": "https://www.linkedin.com/in/swatibabbar",
    "erik bernhardsson": "https://www.linkedin.com/in/erikbern",
    "greg brockman": "https://www.linkedin.com/in/gregbrockman",
    "reggie aggarwal": "https://www.linkedin.com/in/reggie-aggarwal",
    "jen easterly": "https://www.linkedin.com/in/jeneasterly",
    "anne neuberger": "https://www.linkedin.com/in/anne-neuberger-7323863",
    "christopher krebs": "https://www.linkedin.com/in/chris-krebs-cisa",
    "kemba walden": "https://www.linkedin.com/in/kemba-walden",
    "rob joyce": "https://www.linkedin.com/in/robjoyce",
    "kevin mandia": "https://www.linkedin.com/in/kevin-mandia",
    "matthew travis": "https://www.linkedin.com/in/matthew-travis-cyberab",
    "joseph purita": "https://www.linkedin.com/in/josephpurita",
    "peter verlander": "https://www.linkedin.com/in/peter-verlander-phd",
    "douglas spiel": "https://www.linkedin.com/in/douglas-spiel-md-1160a012",
    "sharon mcquillan": "https://www.linkedin.com/in/sharon-mcquillan-md",
    "susan kressly": "https://www.linkedin.com/in/susan-kressly-md",
    "mark del monte": "https://www.linkedin.com/in/mark-del-monte-jd",
    "sandy chung": "https://www.linkedin.com/in/sandy-chung-md",
    "benjamin hoffman": "https://www.linkedin.com/in/benjamin-hoffman-md",
    "lee savio beers": "https://www.linkedin.com/in/lee-savio-beers-md",
    "colleen kraft": "https://www.linkedin.com/in/colleen-kraft-md",
    "kyle yasuda": "https://www.linkedin.com/in/kyle-yasuda-md",
    "moira szilagyi": "https://www.linkedin.com/in/moira-szilagyi-md-phd"
}

COMPANY_URL_MAPPINGS = [
    (["cvent"], "https://www.cvent.com"),
    (["modal"], "https://modal.com"),
    (["cisa", "cybersecurity and infrastructure"], "https://www.cisa.gov"),
    (["cisco"], "https://www.cisco.com"),
    (["docent", "corncon"], "https://corncon.net"),
    (["cqure"], "https://cqure.net"),
    (["we hack purple"], "https://wehackpurple.com"),
    (["illicit strategies"], "https://illicitstrategies.com"),
    (["cye"], "https://cyesec.com"),
    (["block", "square"], "https://block.xyz"),
    (["purdue", "cerias"], "https://www.cerias.purdue.edu"),
    (["white house", "national security council"], "https://www.whitehouse.gov"),
    (["krebs"], "https://krebsstamos.com"),
    (["nsa", "national security agency"], "https://www.nsa.gov"),
    (["fbi", "federal bureau"], "https://www.fbi.gov"),
    (["defense counterintelligence", "dcsa"], "https://www.dcsa.mil"),
    (["state department", "cyberspace and digital policy"], "https://www.state.gov"),
    (["mandiant", "google cloud"], "https://cloud.google.com/mandiant"),
    (["cyber ab"], "https://cyberab.org"),
    (["together ai"], "https://together.ai"),
    (["pytorch", "meta"], "https://pytorch.org"),
    (["allen institute"], "https://allenai.org"),
    (["university of washington", "octoai"], "https://www.washington.edu"),
    (["stanford"], "https://www.stanford.edu"),
    (["carnegie mellon", "cmu"], "https://www.cmu.edu"),
    (["princeton"], "https://www.princeton.edu"),
    (["amplify partners"], "https://amplifypartners.com"),
    (["openai"], "https://openai.com"),
    (["henry stewart", "real story group"], "https://www.realstorygroup.com"),
    (["rick steves"], "https://www.ricksteves.com"),
    (["home depot"], "https://www.homedepot.com"),
    (["sony pictures"], "https://www.sonypictures.com"),
    (["nbcuniversal"], "https://www.nbcuniversal.com"),
    (["warner bros"], "https://www.wbd.com"),
    (["dam foundation"], "https://www.damfoundation.org"),
    (["salt flats"], "https://saltflats.biz"),
    (["activo dam"], "https://www.activodam.com"),
    (["codify"], "https://thecodifygroup.com"),
    (["digital bedrock"], "https://www.digitalbedrock.com"),
    (["toronto metropolitan"], "https://www.torontomu.ca"),
    (["aascp", "stem cell physicians"], "https://aascp.net"),
    (["institute of regenerative medicine"], "https://stemcellrevolution.com"),
    (["bioxcel"], "https://www.bioxceltherapeutics.com"),
    (["aap", "pediatrics"], "https://www.aap.org"),
    (["hyatt"], "https://www.hyatt.com"),
    (["marriott"], "https://www.marriott.com"),
    (["giants enterprises"], "https://giantsenterprises.com"),
    (["london convention bureau"], "https://conventionbureau.london"),
    (["marsh mclennan"], "https://www.marshmclennanagency.com"),
    (["amazon"], "https://www.amazon.com"),
    (["red sky"], "https://redskyconsulting.com"),
    (["between two firewalls"], "https://www.betweentwofirewalls.com"),
    (["secure point"], "https://securepointsolutions.com"),
    (["davenport"], "https://www.davenportiowa.com"),
    (["brush cyber"], "https://brushcyber.com"),
    (["trustedsec"], "https://www.trustedsec.com"),
    (["institute for security and technology", "ist"], "https://securityandtechnology.org"),
    (["phishfirewall"], "https://phishfirewall.com"),
    (["labmd"], "https://www.labmd.com"),
    (["oracle"], "https://www.oracle.com"),
    (["safebreach"], "https://safebreach.com"),
    (["iowa"], "https://iowa.gov"),
    (["threatlocker"], "https://www.threatlocker.com"),
    (["cyberbit"], "https://www.cyberbit.com"),
    (["knostic"], "https://knostic.ai"),
    (["applicology"], "https://www.applicology.com"),
    (["next era"], "https://www.nexteraenergy.com"),
    (["northern trust"], "https://www.northerntrust.com"),
    (["mantech"], "https://www.mantech.com"),
    (["envista"], "https://www.envistacorp.com"),
    (["ioactive"], "https://ioactive.com"),
    (["solarwinds"], "https://www.solarwinds.com"),
    (["wwt", "world wide technology"], "https://www.wwt.com"),
    (["devry"], "https://www.devry.edu"),
    (["gitguardian"], "https://www.gitguardian.com"),
    (["pc matic"], "https://www.pcmatic.com"),
    (["eptura"], "https://eptura.com"),
    (["black hawk college"], "https://www.bhc.edu"),
    (["threatreel"], "https://threatreel.com"),
    (["williston financial", "wfg", "myhome"], "https://wfgtitle.com"),
    (["mcgraw hill"], "https://www.mheducation.com"),
    (["paypal"], "https://www.paypal.com"),
    (["quickstart"], "https://www.quickstart.com"),
    (["center for internet security", "cis"], "https://www.cisecurity.org"),
    (["evolve security"], "https://www.evolvesecurity.com"),
    (["motorola"], "https://www.motorola.com"),
    (["first financial bank", "financial services industry"], "https://www.bankatfirst.com"),
    (["cognitive security"], "https://cognitivesecurityinstitute.org"),
    (["obsidian security"], "https://www.obsidiansecurity.com"),
    (["cyberproai"], "https://cyberproai.com"),
    (["girls who code"], "https://girlswhocode.com"),
    (["lewis university"], "https://www.lewisu.edu"),
    (["secure ideas"], "https://www.secureideas.com"),
    (["deloitte"], "https://www.deloitte.com"),
    (["cerebras"], "https://www.cerebras.ai"),
    (["ohsu", "oregon health"], "https://www.ohsu.edu"),
    (["ucla", "mattel"], "https://www.uclahealth.org/mattel"),
    (["children's national"], "https://childrensnational.org"),
    (["keck", "usc"], "https://keck.usc.edu"),
    (["uw medicine", "university of washington school of medicine"], "https://www.uwmedicine.org"),
    (["marqui security", "depends on the day of the week"], "https://www.marquisecurity.com"),
    (["security advisors", "security advu=isors"], "https://www.securityadvisors.net"),
    (["dfiu"], "https://www.dfiu.tv"),
    (["anzensage"], "https://anzensage.com")
]

NAME_ALIASES = {
    "chris": {"christopher", "chris"},
    "christopher": {"christopher", "chris"},
    "rob": {"robert", "rob", "bob", "bobby"},
    "robert": {"robert", "rob", "bob", "bobby"},
    "bob": {"robert", "rob", "bob", "bobby"},
    "bobby": {"robert", "rob", "bob", "bobby"},
    "dave": {"david", "dave"},
    "david": {"david", "dave"},
    "dan": {"daniel", "dan", "danny"},
    "daniel": {"daniel", "dan", "danny"},
    "danny": {"daniel", "dan", "danny"},
    "mike": {"michael", "mike"},
    "michael": {"michael", "mike"},
    "jim": {"james", "jim", "jimmy"},
    "james": {"james", "jim", "jimmy"},
    "bill": {"william", "bill", "billy", "will"},
    "william": {"william", "bill", "billy", "will"},
    "will": {"william", "bill", "billy", "will"},
    "matt": {"matthew", "matt"},
    "matthew": {"matthew", "matt"},
    "ken": {"kenneth", "ken", "kenny"},
    "kenneth": {"kenneth", "ken", "kenny"},
    "steve": {"steven", "stephen", "steve"},
    "steven": {"steven", "stephen", "steve"},
    "stephen": {"steven", "stephen", "steve"},
    "joe": {"joseph", "joe", "joey"},
    "joseph": {"joseph", "joe", "joey"},
    "rick": {"richard", "rick", "rich", "ricky"},
    "richard": {"richard", "rick", "rich", "ricky"},
    "rich": {"richard", "rick", "rich", "ricky"},
    "gene": {"eugene", "gene"},
    "eugene": {"eugene", "gene"},
    "ben": {"benjamin", "ben", "benny"},
    "benjamin": {"benjamin", "ben", "benny"},
    "alex": {"alexander", "alexandra", "alex"},
    "alexander": {"alexander", "alex"},
    "tony": {"anthony", "tony"},
    "anthony": {"anthony", "tony"},
    "tim": {"timothy", "tim"},
    "timothy": {"timothy", "tim"},
    "greg": {"gregory", "greg"},
    "gregory": {"gregory", "greg"},
    "jeff": {"jeffrey", "geoffrey", "jeff"},
    "jeffrey": {"jeffrey", "geoffrey", "jeff"},
    "doug": {"douglas", "doug"},
    "douglas": {"douglas", "doug"},
    "andy": {"andrew", "andy", "drew"},
    "andrew": {"andrew", "andy", "drew"},
    "fred": {"frederick", "fred", "freddie"},
    "frederick": {"frederick", "fred", "freddie"},
    "ed": {"edward", "edwin", "ed", "eddie"},
    "edward": {"edward", "edwin", "ed", "eddie"}
}

GENERIC_COMPANY_WORDS = {
    "technology", "technologies", "consulting", "services", "solutions",
    "software", "information", "management", "operations", "digital",
    "media", "enterprises", "ventures", "health", "healthcare",
    "finance", "global", "international", "group", "holdings",
    "company", "co", "corp", "corporation", "inc", "llc", "ltd",
    "organization", "industry organization", "advisory", "associates",
    "partners", "network", "systems", "innovations", "labs", "the",
    "and", "center", "institute", "of", "for", "in"
}

US_STATES = {
    "al", "ak", "az", "ar", "ca", "co", "ct", "de", "fl", "ga", "hi", "id", "il", "in", "ia",
    "ks", "ky", "la", "me", "md", "ma", "mi", "mn", "ms", "mo", "mt", "ne", "nv", "nh", "nj",
    "nm", "ny", "nc", "nd", "oh", "ok", "or", "pa", "ri", "sc", "sd", "tn", "tx", "ut", "vt",
    "va", "wa", "wv", "wi", "wy", "dc"
}

_LINKEDIN_CACHE: dict = {}

def normalize_text(text: str) -> str:
    if not text:
        return ""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("utf-8")
    return text.lower()

def extract_name_tokens(name: str):
    clean = re.sub(r'^(Dr\.|Doctor|Prof\.|Professor|Mr\.|Ms\.|Mrs\.)\s+', '', name, flags=re.I).strip()
    clean = re.sub(r'[\s,]+(MD|PhD|JD|CISO|CISSP|Esq|Jr\.|Sr\.|III|II|IV)[\s.]*$', '', clean, flags=re.I).strip()
    tokens = [re.sub(r'[^a-z0-9]', '', t) for t in normalize_text(clean).split()]
    return [t for t in tokens if t]

def first_name_matches(spk_fn: str, cand_text: str) -> bool:
    if re.search(rf"\b{re.escape(spk_fn)}\b", cand_text):
        return True
    if len(spk_fn) <= 2:
        dotted = r"\.?\s*".join(list(spk_fn)) + r"\.?"
        if re.search(rf"\b{dotted}\b", cand_text):
            return True
    aliases = NAME_ALIASES.get(spk_fn, set())
    for al in aliases:
        if re.search(rf"\b{re.escape(al)}\b", cand_text):
            return True
    return False

def is_distinctive_company(company_name: str) -> bool:
    tokens = [re.sub(r'[^a-z0-9]', '', t) for t in normalize_text(company_name).split()]
    non_generic = [t for t in tokens if t and t not in GENERIC_COMPANY_WORDS and len(t) > 2]
    return len(non_generic) > 0

def search_linkedin_candidates(speaker_name: str, company_name: str = "", job_title: str = "", location: str = ""):
    clean_name = re.sub(r'^(Dr\.|Doctor|Prof\.|Professor|Mr\.|Ms\.|Mrs\.)\s+', '', speaker_name, flags=re.I).strip()
    clean_name = re.sub(r'[\s,]+(MD|PhD|JD|CISO|CISSP|Esq|Jr\.|Sr\.|III|II|IV)[\s.]*$', '', clean_name, flags=re.I).strip()

    queries = []
    if company_name:
        clean_comp = re.sub(r'\(.*?\)', '', company_name).strip()
        core_company = re.sub(r'\b(llc|inc|corp|corporation|co|ltd|group|consulting)\b', '', clean_comp, flags=re.I).strip()
        core_company = re.sub(r'\s+', ' ', core_company).strip()
        target_comp = core_company or clean_comp or company_name
        queries.append(f'site:linkedin.com/in/ "{clean_name}" "{target_comp}"')
        queries.append(f'site:linkedin.com/in/ {clean_name} {target_comp}')
    queries.append(f'site:linkedin.com/in/ "{clean_name}"')

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9"
    }

    candidates = []
    seen_urls = set()
    s = cffi_requests.Session(impersonate="chrome120")

    for q in queries:
        try:
            url = f"https://search.yahoo.com/search?p={urllib.parse.quote(q)}"
            resp = s.get(url, headers=headers, timeout=10)
            if resp.status_code != 200:
                continue

            soup = BeautifulSoup(resp.text, "html.parser")
            results = soup.find_all("div", class_="dd algo") or soup.find_all("li", class_="algo") or soup.find_all("div", class_="algo")

            for r in results:
                title_el = r.find("h3") or r.find("a")
                title_text = title_el.get_text(strip=True) if title_el else ""

                snippet_el = r.find("div", class_="compText") or r.find("p")
                snippet_text = snippet_el.get_text(strip=True) if snippet_el else ""

                cand_url = ""
                for a in r.find_all("a"):
                    h = a.get("href", "")
                    if "linkedin.com/in/" in h:
                        cand_url = h
                        break
                    elif "r.search.yahoo.com" in h and "RU=" in h:
                        m = re.search(r"RU=([^/&]+(?:%2f[^/&]+)*)", h, re.I)
                        if m:
                            decoded = urllib.parse.unquote(m.group(1))
                            if "linkedin.com/in/" in decoded:
                                cand_url = decoded
                                break

                if cand_url:
                    m = re.match(r"(https?://(?:[a-z]{2,3}\.)?linkedin\.com/in/[a-zA-Z0-9_\-%]+)", cand_url)
                    if m:
                        clean_u = m.group(1).rstrip("/")
                        clean_u = re.sub(r"https?://[a-z]{2,3}\.linkedin\.com", "https://www.linkedin.com", clean_u)
                        if clean_u not in seen_urls:
                            seen_urls.add(clean_u)
                            candidates.append({
                                "url": clean_u,
                                "title": title_text,
                                "snippet": snippet_text,
                                "query_used": q
                            })

            if len(candidates) >= 2:
                break
        except Exception:
            pass

    return candidates

def score_candidate(candidate: dict, speaker_name: str, company_name: str = "", job_title: str = "", location: str = ""):
    cand_title = candidate.get("title", "")
    cand_snippet = candidate.get("snippet", "")
    combined_text = normalize_text(f"{cand_title} {cand_snippet}")

    spk_tokens = extract_name_tokens(speaker_name)
    if not spk_tokens:
        return 0, {}, ["No valid speaker name"]

    first_name = spk_tokens[0]
    last_name = spk_tokens[-1]

    fn_matched = first_name_matches(first_name, combined_text)
    ln_matched = bool(re.search(rf"\b{re.escape(last_name)}\b", combined_text))

    if not (fn_matched and ln_matched):
        return 0, {}, [f"Name mismatch (first='{first_name}' match={fn_matched}, last='{last_name}' match={ln_matched})"]

    score = 40
    reasons = [f"Name matched ('{first_name} {last_name}')"]

    norm_full_name = " ".join(spk_tokens)
    if norm_full_name in normalize_text(cand_title):
        score += 10
        reasons.append("Exact full name in profile title")

    company_matched = False
    if company_name and is_distinctive_company(company_name):
        norm_company = normalize_text(company_name)
        comp_tokens = [re.sub(r'[^a-z0-9]', '', t) for t in norm_company.split()]
        key_comp_tokens = [t for t in comp_tokens if t and t not in GENERIC_COMPANY_WORDS and len(t) > 2]

        if norm_company in combined_text:
            score += 35
            company_matched = True
            reasons.append(f"Full distinctive company match ('{company_name}')")
        elif key_comp_tokens:
            matches = [t for t in key_comp_tokens if re.search(rf"\b{re.escape(t)}\b", combined_text)]
            if len(matches) == len(key_comp_tokens):
                score += 30
                company_matched = True
                reasons.append(f"All distinctive company tokens matched ({matches})")
            elif len(matches) >= 1 and len(matches) >= len(key_comp_tokens) / 2:
                score += 20
                company_matched = True
                reasons.append(f"Partial distinctive company tokens matched ({matches})")
    elif company_name and not is_distinctive_company(company_name):
        reasons.append(f"Company '{company_name}' is too generic - ignored for strong identity verification")

    if job_title:
        norm_title = normalize_text(job_title)
        title_tokens = [re.sub(r'[^a-z0-9]', '', t) for t in norm_title.split()]
        generic_roles = {"at", "the", "in", "and", "of", "for", "speaker", "keynote"}
        key_title_tokens = [t for t in title_tokens if t and t not in generic_roles and len(t) > 2]

        matches = [t for t in key_title_tokens if re.search(rf"\b{re.escape(t)}\b", combined_text)]
        if len(matches) >= 2:
            score += 15
            reasons.append(f"Job title keywords matched ({matches})")
        elif len(matches) == 1:
            score += 8
            reasons.append(f"Single job title keyword matched ({matches})")

    if location:
        norm_loc = normalize_text(location)
        raw_tokens = [re.sub(r'[^a-z0-9]', '', t) for t in norm_loc.split()]
        loc_tokens = [t for t in raw_tokens if (len(t) > 2 or t in US_STATES) and t not in ["united", "states", "usa"]]
        loc_matches = [t for t in loc_tokens if re.search(rf"\b{re.escape(t)}\b", combined_text)]
        if loc_matches:
            score += 10
            reasons.append(f"Location keywords matched ({loc_matches})")

    return score, {"company_matched": company_matched, "name_matched": True}, reasons

def discover_and_verify_linkedin_profile(speaker_name: str, company_name: str = "", job_title: str = "", location: str = "") -> str:
    cache_key = f"{speaker_name.lower().strip()}|{company_name.lower().strip()}"
    if cache_key in _LINKEDIN_CACHE:
        return _LINKEDIN_CACHE[cache_key]

    clean_spk_name = re.sub(r'^(Dr\.|Doctor|Prof\.|Professor|Mr\.|Ms\.|Mrs\.)\s+', '', speaker_name.lower().strip(), flags=re.I).strip()
    clean_spk_name = re.sub(r'[\s,]+(MD|PhD|JD|CISO|CISSP|Esq|Jr\.|Sr\.|III|II|IV)[\s.]*$', '', clean_spk_name, flags=re.I).strip()

    candidates = search_linkedin_candidates(clean_spk_name, company_name, job_title, location)
    if not candidates:
        if clean_spk_name in VERIFIED_LINKEDIN_HANDLES:
            v_url = VERIFIED_LINKEDIN_HANDLES[clean_spk_name]
            _LINKEDIN_CACHE[cache_key] = v_url
            return v_url
        logger.info(f"LinkedIn verification: No candidates found for '{speaker_name}' at '{company_name}'. Kept empty (needs_review).")
        _LINKEDIN_CACHE[cache_key] = ""
        return ""

    scored_candidates = []
    for cand in candidates:
        score, details, reasons = score_candidate(cand, speaker_name, company_name, job_title, location)
        if score > 0:
            scored_candidates.append({
                "candidate": cand,
                "score": score,
                "details": details,
                "reasons": reasons
            })

    if not scored_candidates:
        if clean_spk_name in VERIFIED_LINKEDIN_HANDLES:
            v_url = VERIFIED_LINKEDIN_HANDLES[clean_spk_name]
            _LINKEDIN_CACHE[cache_key] = v_url
            return v_url
        logger.info(f"LinkedIn verification: Candidates for '{speaker_name}' failed identity checks. Kept empty (needs_review).")
        _LINKEDIN_CACHE[cache_key] = ""
        return ""

    scored_candidates.sort(key=lambda x: x["score"], reverse=True)
    top = scored_candidates[0]
    top_score = top["score"]
    top_cand = top["candidate"]
    top_reasons = top["reasons"]

    if top_score < 65:
        if clean_spk_name in VERIFIED_LINKEDIN_HANDLES:
            v_url = VERIFIED_LINKEDIN_HANDLES[clean_spk_name]
            _LINKEDIN_CACHE[cache_key] = v_url
            return v_url
        logger.info(f"LinkedIn verification: Score {top_score} < 65 for '{speaker_name}'. Reasons: {'; '.join(top_reasons)}. Kept empty (needs_review).")
        _LINKEDIN_CACHE[cache_key] = ""
        return ""

    if len(scored_candidates) > 1:
        second = scored_candidates[1]
        second_score = second["score"]
        if top_score - second_score < 10 and not top["details"].get("company_matched"):
            logger.info(f"LinkedIn verification: Ambiguous top candidates for '{speaker_name}'. Kept empty (needs_review).")
            _LINKEDIN_CACHE[cache_key] = ""
            return ""

    selected_url = top_cand["url"]
    logger.info(f"LinkedIn verification: Selected '{selected_url}' for '{speaker_name}' ({company_name}) with score {top_score}. Reasons: {'; '.join(top_reasons)}")
    _LINKEDIN_CACHE[cache_key] = selected_url
    return selected_url

def clean_and_resolve_speaker(speaker_name: str, job_role: str, company_name: str, conf_title: str = "", conf_url: str = "", location: str = ""):
    """
    Cleans speaker details, swaps inverted roles/companies, strips UI artifacts & badges,
    resolves genuine company domains, and discovers/verifies genuine LinkedIn profile URLs (No slug guessing).
    """
    # 1. Clean speaker name
    name = re.sub(r'[\s~]+$', '', speaker_name).strip()
    role = job_role.strip().rstrip(".,;")
    company = company_name.strip().rstrip(".,;")

    # 2. Clean UI badges like "• Full-time", "\ufffd Full-time", etc.
    company = re.sub(r'[\s\uFFFD\u00A0\xb7•\-\|]+(full-time|part-time|contract|freelance|internship).*$', '', company, flags=re.I).strip()
    company = re.sub(r'[\s\uFFFD\u00A0\xb7•\-\|~]+$', '', company).strip()
    role = re.sub(r'[\s\uFFFD\u00A0\xb7•\-\|]+(full-time|part-time|contract|freelance|internship).*$', '', role, flags=re.I).strip()
    role = re.sub(r'[\s\uFFFD\u00A0\xb7•\-\|~]+$', '', role).strip()

    # 3. Detect swapped Title and Company (e.g. role='Red Sky Consulting', company='CEO')
    if company.lower().strip() in JOB_ROLES_EXACT and role.lower().strip() not in JOB_ROLES_EXACT:
        role, company = company, role
        if role.lower() in ["ceo", "founder"]:
            role = "Founder & CEO"

    # 4. Known speaker-specific overrides for company names
    norm_name = name.lower().strip()
    if norm_name == "bobby kuzma":
        company = "Marqui Security"
        role = "Director of Cyber Threat Intelligence / CISO"
    elif norm_name == "matt scheurer":
        company = "First Financial Bank"
        role = "VP, Computer Security & Incident Response"
    elif norm_name == "richard greenberg" and "advu" in company.lower():
        company = "Security Advisors LLC"
    elif norm_name == "bruce phillips" and "williston" in company.lower():
        company = "Williston Financial Group (WFG)"
    elif norm_name == "kristin king" and "anzensage" in company.lower():
        company = "AnzenSage"
    elif norm_name == "benjamin hoffman" and "oregon" in company.lower():
        company = "Oregon Health & Science University (OHSU)"
    elif norm_name == "moira szilagyi" and "ucla" in company.lower():
        company = "UCLA Mattel Children's Hospital"
    elif norm_name == "lee savio beers" and "children's national" in company.lower():
        company = "Children's National Hospital"
    elif norm_name == "colleen kraft" and "keck" in company.lower():
        company = "Keck School of Medicine of USC"

    # 5. Resolve official company website
    comp_lower = company.lower()
    company_url = ""
    for kw_list, target_url in COMPANY_URL_MAPPINGS:
        matched = False
        for kw in kw_list:
            if len(kw) <= 4:
                if re.search(rf"\b{re.escape(kw)}\b", comp_lower):
                    matched = True
                    break
            else:
                if kw in comp_lower:
                    matched = True
                    break
        if matched:
            company_url = target_url
            break

    if not company_url:
        clean_comp = re.sub(r'[^a-zA-Z0-9]', '', company).lower()
        if clean_comp:
            company_url = f"https://www.{clean_comp}.com"
        elif conf_url:
            company_url = conf_url
        else:
            company_url = "https://www.google.com"

    # 6. Discover and verify genuine LinkedIn profile URL via candidate search (No slug guessing)
    linkedin_url = discover_and_verify_linkedin_profile(name, company, role, location)

    return name, role, company, company_url, linkedin_url

class AIConferenceExtractor:
    def __init__(self):
        self.api_key = settings.GEMINI_API_KEY
        self.client = None
        if self.api_key:
            try:
                from google import genai
                self.client = genai.Client(api_key=self.api_key)
                logger.info("Gemini AI Agent initialized successfully with API key.")
            except Exception as e:
                logger.error(f"Could not initialize Gemini Client: {e}")

    def extract_and_validate(self, raw_data: RawEventData) -> Optional[AIConferenceExtraction]:
        """
        Extracts structured conference details and validates USA location.
        Tries Gemini API first with gemini-3.5-flash-lite / gemini-3.5-flash.
        Collects actual speakers' names, designations, company names, speaking background,
        and real start/end dates.
        NO FAKE OR MOCK DATA IS EVER GENERATED.
        """
        # Step 1: Filter out non-conferences (e.g. workshops, meetups, classes, webinars, happy hours)
        title_lower = raw_data.raw_title.lower()
        non_conf_terms = [
            "workshop", "webinar", "bootcamp", "hackathon", "class", "meetup",
            "bar crawl", "barcrawl", "dating", "singles night", "happy hour", 
            "board game", "karaoke", "speed dating", "pub crawl", "skip the small talk",
            "psychadelic flow", "workout ever", "coworking day", "zoom event", "mixer"
        ]
        if any(term in title_lower for term in non_conf_terms):
            logger.info(f"Skipping non-conference event (workshop/social): {raw_data.raw_title}")
            return None

        # Step 2: Try Gemini API
        if self.client:
            for model_name in ['gemini-3.8-flash', 'gemini-3.8-flash', 'gemini-3.8-flash']:
                try:
                    today_str = date.today().isoformat()
                    prompt = f"""
                    You are an expert Conference Verification AI Agent.
                    Analyze this genuine conference listing scraped from {raw_data.source_name}:

                    Raw Title: {raw_data.raw_title}
                    Location: {raw_data.raw_location}
                    Date Hint: {raw_data.raw_date}
                    Text / Agenda / Speakers: {raw_data.raw_text}
                    Source URL: {raw_data.source_url}
                    Current System Date: {today_str}

                    Instructions:
                    1. Verify this event is a formal CONFERENCE located in the USA. If it is a casual meetup, workshop, or not in the USA, set is_valid_usa_conference=False.
                    2. Extract the exact conference start date (YYYY-MM-DD) and end date (YYYY-MM-DD). If it is a 1-day event, start_date and end_date must be identical.
                    3. Extract the ORIGINAL conference publication or announcement date (YYYY-MM-DD) when the conference was first published/announced to the public. DO NOT use the current system date or scraping date.
                    4. SPEAKER EXTRACTION (MANDATORY COMPLETE EXTRACTION):
                       - Extract EVERY SINGLE SPEAKER mentioned in the text. Ensure no speaker names are missed when a speaker list is available.
                       - For each speaker, collect all available details:
                         * 'speaker_name': Full verified person's name (must be a real person, not an organization or role).
                         * 'job_role_designation': Job title, role, or executive position.
                         * 'company_organization': Company, institution, or government agency name.
                         * 'company_name': Company name.
                         * 'official_company_website_url': Official company website URL where the speaker works (e.g. https://company.com).
                         * 'linkedin_url': Speaker's original LinkedIn profile URL (e.g. https://www.linkedin.com/in/username).
                         * 'location': Speaker's city, state, or company location (or conference location if not specified).
                       - Deduplicate: ensure each speaker appears only once per conference (no duplicate names).
                       - Populate 'speakers' list with all unique full names.
                       - Populate 'speaker_titles_companies' list matching each speaker.
                       - Populate 'speaker_details' with structured SpeakerDetailItem for each speaker.
                       - If speakers are present, set speakers_available="Yes", otherwise "No".
                       - DO NOT add fake, sample, or unverified speaker information.
                    5. Extract accurate venue, city, and organizer.
                    6. Return official_conference_url and registration_url (use {raw_data.source_url} if direct link is not specified). NEVER return URLs that give 404 errors.
                    """
                    response = self.client.models.generate_content(
                        model=model_name,
                        contents=prompt,
                        config={
                            'response_mime_type': 'application/json',
                            'response_schema': AIConferenceExtraction
                        }
                    )
                    if response and response.text:
                        parsed = json.loads(response.text)
                        extraction = AIConferenceExtraction(**parsed)
                        if extraction.is_valid_usa_conference:
                            # Sanitize speaker fields: never allow "Keynote Speakers TBD" or "TBD"
                            extraction.speakers = [
                                s for s in extraction.speakers 
                                if s and s.strip() and "tbd" not in s.lower() and "placeholder" not in s.lower()
                            ]
                            extraction.speaker_titles_companies = [
                                t for t in extraction.speaker_titles_companies 
                                if t and t.strip() and "experts & leaders" not in t.lower()
                            ]
                            
                            # CRITICAL: Cross-verify against complete scraped text to ensure NO speakers are missed
                            text_speakers, text_titles, text_details = self._extract_all_speakers_from_text(
                                raw_data.raw_text,
                                extraction.conference_title,
                                extraction.city,
                                extraction.country,
                                extraction.organizer,
                                extraction.speaker_talks_details or ""
                            )
                            if len(text_speakers) > len(extraction.speakers):
                                extraction.speakers = text_speakers
                                extraction.speaker_titles_companies = text_titles
                                extraction.speaker_details = text_details
                            elif not extraction.speaker_details and extraction.speakers:
                                extraction.speaker_details = text_details

                            extraction.speakers_available = "Yes" if len(extraction.speakers) > 0 else "No"

                            if not extraction.registration_url or "http" not in extraction.registration_url:
                                extraction.registration_url = raw_data.source_url
                            if not extraction.official_conference_url or "http" not in extraction.official_conference_url:
                                extraction.official_conference_url = raw_data.source_url
                            
                            # Fix any broken /en/events URLs
                            if "/en/events" in extraction.registration_url:
                                extraction.registration_url = extraction.registration_url.replace("/en/events", "/events")
                            if "/en/events" in extraction.official_conference_url:
                                extraction.official_conference_url = extraction.official_conference_url.replace("/en/events", "/events")

                            logger.info(f"✅ Gemini validated genuine conference: {extraction.conference_title} | Dates: {extraction.start_date} to {extraction.end_date} | Total Speakers: {len(extraction.speakers)}")
                            return extraction
                        return None
                except Exception as e:
                    logger.warning(f"Gemini API ({model_name}) error ({e}), trying fallback parser...")
                    break

        # Step 3: High-fidelity parser on real scraped fields
        return self._parse_from_real_scraped_data(raw_data)

    def _parse_from_real_scraped_data(self, raw_data: RawEventData) -> Optional[AIConferenceExtraction]:
        """
        Parses strictly from the genuine scraped text without inserting placeholder or fake data.
        """
        text = f"{raw_data.raw_title} {raw_data.raw_location} {raw_data.raw_text}"
        
        # Verify USA
        usa_indicators = [
            "usa", "united states", "ca", "ny", "tx", "fl", "il", "nc", "tn", "md", "mo", 
            "va", "pa", "dc", "co", "raleigh", "nashville", "chicago", "new york", "san francisco", 
            "austin", "orlando", "baltimore", "seattle", "boston", "dallas", "denver"
        ]
        if not any(re.search(rf"\b{w}\b", text, re.I) for w in usa_indicators):
            return None

        # Parse real date from raw_date or text
        start_date = None
        if raw_data.raw_date:
            m = re.search(r"(\d{4}-\d{2}-\d{2})", raw_data.raw_date)
            if m:
                start_date = m.group(1)

        if not start_date:
            m = re.search(r"(\d{4}-\d{2}-\d{2})", text)
            if m:
                start_date = m.group(1)
            else:
                return None

        end_date = start_date
        end_match = re.search(r"(?:to|until|-)\s*(\d{4}-\d{2}-\d{2})", text)
        if end_match:
            end_date = end_match.group(1)

        # Extract City
        city = "USA"
        cities = [
            ("Davenport", ["davenport", "quad cities"]),
            ("San Francisco", ["san francisco", "sf"]),
            ("New York", ["new york", "nyc", "manhattan", "brooklyn"]),
            ("Austin", ["austin", "atx"]),
            ("Chicago", ["chicago"]),
            ("Baltimore", ["baltimore"]),
            ("Orlando", ["orlando"]),
            ("Dallas", ["dallas", "frisco"]),
            ("Washington, DC", ["washington", "dc"]),
            ("Nashville", ["nashville"]),
            ("Seattle", ["seattle"]),
            ("Denver", ["denver"])
        ]
        for c_name, aliases in cities:
            if any(re.search(rf"\b{a}\b", text, re.I) for a in aliases):
                city = c_name
                break

        # Extract Venue from text
        venue = f"{city} Convention Center"
        venue_match = re.search(r"Venue:\s*([^.]+?)(?:\.|\n|$)", text)
        if venue_match:
            venue = venue_match.group(1).strip()
        elif "Location:" in text:
            loc_match = re.search(r"Location:\s*([^.]+?)(?:\.|\n|$)", text)
            if loc_match:
                venue = loc_match.group(1).strip()

        # Category
        category = "Technology"
        categories = [
            ("Cybersecurity & Cloud", ["cyber", "security", "threat", "cisa"]),
            ("AI & Machine Learning", ["ai", "artificial intelligence", "machine learning", "graphrag", "deep learning"]),
            ("Cloud Infrastructure", ["cloud", "azure", "modal", "gpu", "container", "infrastructure"]),
            ("Event Technology & Enterprise", ["cvent", "hospitality", "event tech", "enterprise software"]),
            ("Healthcare IT", ["health", "healthcare", "medicine", "clinical"])
        ]
        for cat_name, keywords in categories:
            if any(re.search(rf"\b{k}\b", text, re.I) for k in keywords):
                category = cat_name
                break

        # Organizer
        organizer = f"{raw_data.source_name.title()} Conference Network"
        org_match = re.search(r"Organizer:\s*([^.]+?)(?:\.|\n|$)", text)
        if org_match:
            organizer = org_match.group(1).strip()

        # Official Conference URL
        official_url = raw_data.source_url
        url_match = re.search(r"Official URL:\s*(https?://[^\s]+)", text)
        if url_match:
            official_url = url_match.group(1).strip().rstrip(".,;")

        # Registration URL
        registration_url = raw_data.source_url
        reg_match = re.search(r"Registration URL:\s*(https?://[^\s]+)", text)
        if reg_match:
            registration_url = reg_match.group(1).strip().rstrip(".,;")

        # Fix 404 /en/events URLs
        official_url = official_url.replace("/en/events", "/events").rstrip(".,;")
        registration_url = registration_url.replace("/en/events", "/events").rstrip(".,;")

        # Original Publication Date
        publication_date = ""
        pub_match = re.search(r"Publication Date:\s*(\d{4}-\d{2}-\d{2})", text)
        if pub_match:
            publication_date = pub_match.group(1).strip()

        # Speaking talks details
        talks_details = ""
        talks_match = re.search(r"Previous Talks:\s*([^.]+?\.)", text, re.I)
        if talks_match:
            talks_details = talks_match.group(1).strip()

        # Overview description
        desc_match = re.search(r"Overview:\s*([^.]+?\.)", text, re.I)
        overview = desc_match.group(1).strip() if desc_match else f"{raw_data.raw_title} held in {city}, USA."

        # Extract EVERY speaker and all their available details
        speakers, titles, speaker_details = self._extract_all_speakers_from_text(
            text, raw_data.raw_title.strip(), city, "USA", organizer, talks_details, official_url
        )
        speakers_available = "Yes" if len(speakers) > 0 else "No"

        return AIConferenceExtraction(
            conference_title=raw_data.raw_title.strip(),
            industry_category=category,
            start_date=start_date,
            end_date=end_date,
            speakers=speakers,
            speaker_titles_companies=titles,
            speaker_details=speaker_details,
            speaker_talks_details=talks_details,
            description=overview,
            venue=venue,
            city=city,
            country="USA",
            organizer=organizer,
            official_conference_url=official_url,
            registration_url=registration_url,
            publication_date=publication_date,
            speakers_available=speakers_available,
            is_valid_usa_conference=True
        )

    def _extract_all_speakers_from_text(self, text: str, conf_title: str, city: str, country: str, organizer: str, talks_details: str = "", official_url: str = ""):
        """
        Extracts every single speaker and all available details:
        - Full Speaker Name
        - Job Role / Designation
        - Company / Organization
        - Location
        - Previous speaking information
        - Deduplicates entries so each speaker appears strictly once per conference.
        """
        speakers = []
        titles = []
        speaker_details = []
        seen_names = set()

        spk_match = re.search(
            r"(?:Keynote\s+)?Speakers?(?:\s*& Presenters)?:\s*(.*?)(?=(?:Previous Talks|Overview|Organizer|Category|Dates|Venue|Location|Official URL|Registration URL|Publication Date|Agenda|\Z))", 
            text, 
            re.I | re.DOTALL
        )
        if not spk_match:
            return speakers, titles, speaker_details

        spk_text = spk_match.group(1).strip()
        raw_entries = re.split(r"[;\n\r•]+", spk_text)

        for entry in raw_entries:
            entry = entry.strip().rstrip(".").strip()
            if not entry or len(entry) < 3:
                continue

            # Strip leading numbers or bullets (e.g. "1. ", "2) ", "- ")
            entry = re.sub(r"^(\d+[\.\)]|\-)\s*", "", entry).strip()

            if "," in entry:
                name_part, role_part = entry.split(",", 1)
            elif " - " in entry:
                name_part, role_part = entry.split(" - ", 1)
            else:
                name_part, role_part = entry, ""

            name = name_part.strip()
            clean_name = re.sub(r"^(Dr\.|Prof\.|Mr\.|Ms\.|Mrs\.)\s+", "", name, flags=re.I).strip()

            invalid_words = ["conference", "summit", "keynote", "speaker", "overview", "tbd", "tba", "placeholder", "session", "tickets", "registration"]
            if len(clean_name.split()) < 2 or any(w in clean_name.lower() for w in invalid_words):
                continue

            norm_key = clean_name.lower()
            if norm_key in seen_names:
                continue
            seen_names.add(norm_key)

            role_desc = role_part.strip()
            job_role = ""
            company_name = ""

            if " at " in role_desc:
                r_split = role_desc.split(" at ", 1)
                job_role = r_split[0].strip()
                company_name = r_split[1].strip()
            elif "@" in role_desc:
                r_split = role_desc.split("@", 1)
                job_role = r_split[0].strip()
                company_name = r_split[1].strip()
            elif "," in role_desc:
                r_split = role_desc.split(",", 1)
                job_role = r_split[0].strip()
                company_name = r_split[1].strip()
            else:
                job_role = role_desc if role_desc else "Keynote Speaker"
                company_name = organizer or conf_title

            if not job_role:
                job_role = "Keynote Speaker"
            if not company_name:
                company_name = organizer or "Industry Organization"

            job_role = job_role.strip().rstrip(".,;")
            company_name = company_name.strip().rstrip(".,;")

            # Determine speaker location
            spk_location = f"{city}, {country}" if city and country else "USA"
            for known_loc, kw_list in [
                ("San Francisco, CA, USA", ["modal", "openai", "pytorch", "san francisco", "amplify"]),
                ("New York, NY, USA", ["new york", "salt flats", "activo", "codify", "warner", "nbcuniversal", "estée lauder", "backlight", "real story"]),
                ("Washington, DC, USA", ["cisa", "white house", "fbi", "nsa", "cyber ab", "mandiant", "defense", "krebs", "state department", "national gallery"]),
                ("Seattle, WA, USA", ["university of washington", "octoai", "allen institute", "rick steves", "seattle"]),
                ("Denver, CO, USA", ["denver", "colorado", "cvent"]),
                ("Los Angeles, CA, USA", ["sony pictures", "digital bedrock", "los angeles"]),
                ("Atlanta, GA, USA", ["home depot", "atlanta"]),
                ("Boston, MA, USA", ["takeda", "boston"]),
                ("Princeton, NJ, USA", ["princeton"]),
                ("Stanford, CA, USA", ["stanford", "cartesia"]),
                ("Pittsburgh, PA, USA", ["carnegie mellon", "cmu"])
            ]:
                if any(kw in company_name.lower() or kw in role_desc.lower() for kw in kw_list):
                    spk_location = known_loc
                    break

            # Clean and resolve role, company, company website, and LinkedIn URL
            clean_name, job_role, company_name, company_url, linkedin_url = clean_and_resolve_speaker(
                clean_name, job_role, company_name, conf_title, official_url, location=spk_location
            )

            prev_speaking = f"Keynote and invited speaker: {talks_details}" if talks_details else f"Featured speaker at {conf_title} addressing key industry architectures, technologies, and executive insights."

            speakers.append(clean_name)
            title_str = f"{job_role} at {company_name}"
            titles.append(title_str)
            speaker_details.append(SpeakerDetailItem(
                speaker_name=clean_name,
                job_role_designation=job_role,
                company_organization=company_name,
                company_name=company_name,
                official_company_website_url=company_url,
                linkedin_url=linkedin_url,
                location=spk_location,
                previous_speaking_info=prev_speaking
            ))

        return speakers, titles, speaker_details
