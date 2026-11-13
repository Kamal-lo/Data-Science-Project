"""
Schéma Pydantic V2 du profil entreprise pour la réponse aux marchés publics marocains.
Conforme au Décret n° 2-22-431 relatif aux marchés publics.

Utilisé par :
- P6 (FastAPI /companies, Go/No-Go T32, PostgreSQL T07)
- P5 (Scoring de pertinence des avis T73)
- P3 (Corpus pour le RAG du mémoire technique T40)
- P4 (Vérification de conformité réglementaire T55)
- P1 (Variables candidats pour le Win-Rate T80)
"""

from __future__ import annotations
from typing import List, Optional, Literal
from datetime import date
from uuid import UUID, uuid4
from pydantic import BaseModel, Field, EmailStr, HttpUrl, field_validator
import re


class RegistreCommerce(BaseModel):
    numero: str = Field(..., description="Numéro d'immatriculation au RC")
    tribunal_ville: str = Field(..., description="Ville du Tribunal de Commerce")


class IdentificationAdministrative(BaseModel):
    raison_sociale: str = Field(..., min_length=2, description="Dénomination légale de l'entreprise")
    nom_commercial: Optional[str] = None
    forme_juridique: Literal["SARL", "SARL_AU", "SA", "SAS", "SNC", "GROUPEMENT", "COOPERATIVE", "AUTO_ENTREPRENEUR"]
    ice: str = Field(..., description="Identifiant Commun de l'Entreprise (15 chiffres)")
    identifiant_fiscal: str = Field(..., description="Identifiant Fiscal délivré par la DGI")
    registre_commerce: RegistreCommerce
    numero_patente: str = Field(..., description="Numéro de taxe professionnelle / patente")
    numero_affiliation_cnss: str = Field(..., description="Numéro d'affiliation à la CNSS")
    date_creation: date
    capital_social_mad: float = Field(..., ge=0, description="Capital social libéré en Dirhams")
    statut_pme: bool = Field(default=True, description="Éligibilité au statut PME (quota 20%)")
    eligibilite_preference_nationale: bool = Field(default=True, description="Majoration 15% préférence nationale")

    @field_validator("ice")
    @classmethod
    def validate_ice(cls, v: str) -> str:
        if not re.match(r"^[0-9]{15}$", v):
            raise ValueError("L'ICE doit comporter exactement 15 chiffres numériques.")
        return v

    @field_validator("identifiant_fiscal")
    @classmethod
    def validate_if(cls, v: str) -> str:
        if not re.match(r"^[0-9]{7,10}$", v):
            raise ValueError("L'Identifiant Fiscal doit comporter entre 7 et 10 chiffres.")
        return v


class RepresentantLegal(BaseModel):
    nom: str
    prenom: str
    cin: str = Field(..., description="Carte d'Identité Nationale marocaine")
    nationalite: str = "Marocaine"
    qualite: str = Field(..., description="Qualité : Gérant, PDG, etc.")
    pouvoir_signataire: Literal["STATUTS", "PROCURATION_NOTARIEE", "DELIBERATION_CONSEIL"]
    email_notification: EmailStr
    telephone_mobile: str = Field(..., pattern=r"^(\+212|0)[5-7][0-9]{8}$")


class Coordonnees(BaseModel):
    adresse_siege: str
    complement_adresse: Optional[str] = None
    ville: str
    code_postal: str = Field(..., pattern=r"^[0-9]{5}$")
    region: Literal[
        "Tanger-Tétouan-Al Hoceïma",
        "L'Oriental",
        "Fès-Meknès",
        "Rabat-Salé-Kénitra",
        "Béni Mellal-Khénifra",
        "Casablanca-Settat",
        "Marrakech-Safi",
        "Drâa-Tafilalet",
        "Souss-Massa",
        "Guelmim-Oued Noun",
        "Laâyoune-Sakia El Hamra",
        "Dakhla-Oued Ed-Dahab"
    ]
    telephone_fixe: str
    email_officiel: EmailStr
    site_web: Optional[HttpUrl] = None


class CertificatBTP(BaseModel):
    secteur: str = Field(..., description="Secteur officiel (ex: Secteur A, B, C...)")
    libelle_secteur: str
    classe: int = Field(..., ge=1, le=5, description="Classe de 1 à 5")
    categories: List[str] = Field(default_factory=list, description="Ex: ['A.1', 'A.2']")
    numero_certificat: str
    date_delivrance: date
    date_expiration: date


class AgrementEtudes(BaseModel):
    domaine_code: str = Field(..., description="Ex: D1, D2, D8...")
    domaine_libelle: str
    numero_agrement: str
    date_expiration: date


class CertificationNorme(BaseModel):
    norme: str = Field(..., description="Ex: ISO 9001:2015, ISO 27001:2022")
    organisme_certificateur: str
    numero_certificat: str
    date_expiration: date


class QualificationsEtCertifications(BaseModel):
    certificats_btp: List[CertificatBTP] = Field(default_factory=list)
    agrements_etudes: List[AgrementEtudes] = Field(default_factory=list)
    certifications_normes: List[CertificationNorme] = Field(default_factory=list)


class BilanExercice(BaseModel):
    exercice_annee: int = Field(..., ge=2018, le=2035)
    chiffre_affaires_global_mad: float = Field(..., ge=0)
    chiffre_affaires_secteur_mad: float = Field(..., ge=0)
    resultat_net_mad: float
    capitaux_propres_mad: float
    tresorerie_nette_mad: float = 0.0
    certifie_par_commissaire_aux_comptes: bool = True


class LigneBancaireCaution(BaseModel):
    banque: str = Field(..., description="Nom de la banque marocaine partenaire")
    agence: str
    plafond_caution_mad: float = Field(..., ge=0)
    encours_disponible_mad: float = Field(..., ge=0)


class CapacitesFinancieres(BaseModel):
    bilans_3_derniers_exercices: List[BilanExercice] = Field(..., min_length=1)
    chiffre_affaires_moyen_3_ans_mad: float = Field(..., ge=0)
    lignes_bancaires_caution: List[LigneBancaireCaution] = Field(default_factory=list)


class PersonnelCleExpert(BaseModel):
    id: str
    nom_complet: str
    cin: str
    role_titre: str
    niveau_etudes: Literal["BAC+2", "BAC+3", "BAC+5_INGENIEUR", "BAC+5_MASTER", "DOCTORAT"]
    diplome: str
    ecole_universite: str
    annees_experience_totale: float = Field(..., ge=0)
    annees_experience_specifique: float = Field(..., ge=0)
    competences_cles: List[str] = Field(default_factory=list)
    date_immatriculation_cnss: Optional[date] = None
    resume_cv: str = Field(..., description="Texte de synthèse prêt pour le RAG")


class MoyensHumains(BaseModel):
    effectif_total_declare_cnss: int = Field(..., ge=1)
    cadres_et_ingenieurs: int = Field(default=0, ge=0)
    techniciens_et_agents_maitrise: int = Field(default=0, ge=0)
    ouvriers_et_employes: int = Field(default=0, ge=0)
    personnel_cle_experts: List[PersonnelCleExpert] = Field(default_factory=list)


class MaterielItem(BaseModel):
    id: str
    designation: str
    categorie: Literal[
        "ENGIN_CHANTIER",
        "VEHICULE_UTILITAIRE",
        "SERVEUR_DATA_CENTER",
        "MATERIEL_MESURE_LABO",
        "POSTE_TRAVAIL_INFORMATIQUE",
        "LICENCE_LOGICIEL_SPECIALISE",
        "AUTRE"
    ]
    marque_modele: str
    immatriculation_ou_numero_serie: Optional[str] = None
    annee_acquisition: int
    statut_possession: Literal["PLEINE_PROPRIETE", "CREDIT_BAIL_LEASING", "LOCATION_LONGUE_DUREE"]
    etat_fonctionnel: Literal["EXCELLENT", "BON", "MOYEN"] = "EXCELLENT"


class MoyensMateriels(BaseModel):
    parc_materiel: List[MaterielItem] = Field(default_factory=list)


class ReferenceSimilaire(BaseModel):
    id: str
    client_nom: str
    client_type: Literal["PUBLIC", "SEMI_PUBLIC", "PRIVE"]
    numero_marche: Optional[str] = None
    intitule_projet: str
    description_prestations: str
    secteur_nomenclature: str
    montant_marche_mad: float = Field(..., ge=0)
    part_realisee_pourcentage: float = Field(default=100.0, ge=1.0, le=100.0)
    annee_debut: int
    annee_fin: int
    attestation_bonne_fin_disponible: bool = True
    signataire_attestation: Optional[str] = None
    mots_cles_techniques: List[str] = Field(default_factory=list)


class PreferencesVeilleEtStrategie(BaseModel):
    domaines_cibles: List[str]
    regions_cibles: List[str]
    types_marches_exclus: List[str] = Field(default_factory=list)
    montant_min_souhaite_mad: float = Field(default=0.0, ge=0)
    montant_max_souhaite_mad: float = Field(default=100_000_000.0, ge=0)
    taux_marge_cible_pourcentage: float = Field(default=18.0, ge=0, le=100)
    tolerance_risque_financier: Literal["FAIBLE", "MOYENNE", "ELEVEE"] = "MOYENNE"
    canaux_alertes: dict = Field(default_factory=lambda: {"email": True, "telegram": False, "whatsapp": True})


class EntrepriseProfile(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    identification_administrative: IdentificationAdministrative
    representant_legal: RepresentantLegal
    coordonnees: Coordonnees
    qualifications_et_certifications: QualificationsEtCertifications
    capacites_financieres: CapacitesFinancieres
    moyens_humains: MoyensHumains
    moyens_materiels: MoyensMateriels
    references_similaires: List[ReferenceSimilaire] = Field(default_factory=list)
    preferences_veille_et_strategie: PreferencesVeilleEtStrategie

