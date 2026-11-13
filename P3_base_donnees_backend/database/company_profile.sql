-- ==============================================================================
-- SCHEMA POSTGRESQL 16 + PGVECTOR : PROFIL ENTREPRISE (MARCHES PUBLICS MAROC)
-- Conforme au Décret n° 2-22-431
-- Livrable T02 (P1) pour le socle base de données T07 (P6)
-- ==============================================================================

-- Activation des extensions requises
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "vector";

-- 1. Table principale : Entreprise et identification administrative
CREATE TABLE IF NOT EXISTS companies (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    raison_sociale VARCHAR(255) NOT NULL,
    nom_commercial VARCHAR(255),
    forme_juridique VARCHAR(50) NOT NULL CHECK (
        forme_juridique IN ('SARL', 'SARL_AU', 'SA', 'SAS', 'SNC', 'GROUPEMENT', 'COOPERATIVE', 'AUTO_ENTREPRENEUR')
    ),
    ice CHAR(15) UNIQUE NOT NULL,
    identifiant_fiscal VARCHAR(20) NOT NULL,
    rc_numero VARCHAR(50) NOT NULL,
    rc_tribunal_ville VARCHAR(100) NOT NULL,
    numero_patente VARCHAR(50) NOT NULL,
    numero_affiliation_cnss VARCHAR(50) NOT NULL,
    date_creation DATE NOT NULL,
    capital_social_mad NUMERIC(15, 2) NOT NULL DEFAULT 0.00,
    statut_pme BOOLEAN NOT NULL DEFAULT TRUE,
    eligibilite_preference_nationale BOOLEAN NOT NULL DEFAULT TRUE,
    
    -- Coordonnées siège
    adresse_siege TEXT NOT NULL,
    complement_adresse TEXT,
    ville VARCHAR(100) NOT NULL,
    code_postal CHAR(5) NOT NULL,
    region VARCHAR(100) NOT NULL,
    telephone_fixe VARCHAR(50) NOT NULL,
    email_officiel VARCHAR(255) NOT NULL,
    site_web VARCHAR(255),

    -- Représentant légal
    rep_nom VARCHAR(100) NOT NULL,
    rep_prenom VARCHAR(100) NOT NULL,
    rep_cin VARCHAR(20) NOT NULL,
    rep_nationalite VARCHAR(50) DEFAULT 'Marocaine',
    rep_qualite VARCHAR(100) NOT NULL,
    rep_pouvoir_signataire VARCHAR(50) NOT NULL CHECK (
        rep_pouvoir_signataire IN ('STATUTS', 'PROCURATION_NOTARIEE', 'DELIBERATION_CONSEIL')
    ),
    rep_email VARCHAR(255) NOT NULL,
    rep_telephone VARCHAR(50) NOT NULL,

    chiffre_affaires_moyen_3_ans_mad NUMERIC(15, 2) DEFAULT 0.00,
    effectif_total_cnss INTEGER DEFAULT 1,

    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_companies_ice ON companies(ice);
CREATE INDEX IF NOT EXISTS idx_companies_region ON companies(region);

-- 2. Qualifications et Agréments ministériels (BTP & Études)
CREATE TABLE IF NOT EXISTS company_qualifications (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    type_qualification VARCHAR(50) NOT NULL CHECK (type_qualification IN ('BTP_MINISTERE', 'BUREAU_ETUDES', 'CERTIFICATION_ISO', 'AUTRE')),
    code_secteur_ou_domaine VARCHAR(50) NOT NULL, -- Ex: 'Secteur B', 'D1', 'ISO 9001:2015'
    libelle VARCHAR(255) NOT NULL,
    classe INTEGER CHECK (classe BETWEEN 1 AND 5), -- Pour le BTP (1 à 5)
    categories JSONB DEFAULT '[]'::jsonb, -- Liste des catégories sous forme JSON
    numero_certificat VARCHAR(100) NOT NULL,
    organisme_delivrance VARCHAR(150) NOT NULL, -- IMANOR, Ministère Équipement...
    date_delivrance DATE,
    date_expiration DATE NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_company_qualif_company ON company_qualifications(company_id);
CREATE INDEX IF NOT EXISTS idx_company_qualif_code ON company_qualifications(code_secteur_ou_domaine);

-- 3. Historique financier et bilans
CREATE TABLE IF NOT EXISTS company_financials (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    exercice_annee INTEGER NOT NULL CHECK (exercice_annee >= 2015),
    chiffre_affaires_global_mad NUMERIC(15, 2) NOT NULL,
    chiffre_affaires_secteur_mad NUMERIC(15, 2) NOT NULL,
    resultat_net_mad NUMERIC(15, 2) NOT NULL,
    capitaux_propres_mad NUMERIC(15, 2) NOT NULL,
    tresorerie_nette_mad NUMERIC(15, 2) DEFAULT 0.00,
    certifie_par_commissaire BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(company_id, exercice_annee)
);

CREATE INDEX IF NOT EXISTS idx_company_financials_year ON company_financials(company_id, exercice_annee DESC);

-- 4. Lignes de cautionnement bancaire
CREATE TABLE IF NOT EXISTS company_bank_lines (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    banque_nom VARCHAR(150) NOT NULL,
    agence VARCHAR(150) NOT NULL,
    plafond_caution_mad NUMERIC(15, 2) NOT NULL,
    encours_disponible_mad NUMERIC(15, 2) NOT NULL,
    date_mise_a_jour DATE DEFAULT CURRENT_DATE
);

-- 5. Personnel clé et experts (avec embedding pour le RAG du mémoire technique)
CREATE TABLE IF NOT EXISTS company_personnel (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    nom_complet VARCHAR(200) NOT NULL,
    cin VARCHAR(20) NOT NULL,
    role_titre VARCHAR(150) NOT NULL,
    niveau_etudes VARCHAR(50) NOT NULL,
    diplome VARCHAR(200) NOT NULL,
    ecole_universite VARCHAR(200) NOT NULL,
    annees_experience_totale NUMERIC(4, 1) NOT NULL,
    annees_experience_specifique NUMERIC(4, 1) NOT NULL,
    competences_cles JSONB DEFAULT '[]'::jsonb,
    date_immatriculation_cnss DATE,
    resume_cv TEXT NOT NULL,
    cv_embedding vector(1536), -- Pour le RAG P3
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_company_personnel_company ON company_personnel(company_id);

-- 6. Parc matériel et logistique
CREATE TABLE IF NOT EXISTS company_equipment (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    designation VARCHAR(255) NOT NULL,
    categorie VARCHAR(100) NOT NULL,
    marque_modele VARCHAR(150) NOT NULL,
    immatriculation_ou_serie VARCHAR(100),
    annee_acquisition INTEGER NOT NULL,
    statut_possession VARCHAR(50) NOT NULL CHECK (statut_possession IN ('PLEINE_PROPRIETE', 'CREDIT_BAIL_LEASING', 'LOCATION_LONGUE_DUREE')),
    etat_fonctionnel VARCHAR(50) DEFAULT 'EXCELLENT',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 7. Références similaires et réalisations passées (avec embedding)
CREATE TABLE IF NOT EXISTS company_references (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    client_nom VARCHAR(200) NOT NULL,
    client_type VARCHAR(50) NOT NULL CHECK (client_type IN ('PUBLIC', 'SEMI_PUBLIC', 'PRIVE')),
    numero_marche VARCHAR(100),
    intitule_projet VARCHAR(255) NOT NULL,
    description_prestations TEXT NOT NULL,
    secteur_nomenclature VARCHAR(100) NOT NULL,
    montant_marche_mad NUMERIC(15, 2) NOT NULL,
    part_realisee_pct NUMERIC(5, 2) DEFAULT 100.00,
    annee_debut INTEGER NOT NULL,
    annee_fin INTEGER NOT NULL,
    attestation_bonne_fin_disponible BOOLEAN DEFAULT TRUE,
    signataire_attestation VARCHAR(150),
    mots_cles JSONB DEFAULT '[]'::jsonb,
    reference_embedding vector(1536), -- Pour le matching sémantique P3 et P5
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_company_refs_company ON company_references(company_id);

-- 8. Préférences de veille et alertes (pour Module A - P5 et Module F - P1)
CREATE TABLE IF NOT EXISTS company_tender_preferences (
    company_id UUID PRIMARY KEY REFERENCES companies(id) ON DELETE CASCADE,
    domaines_cibles JSONB NOT NULL DEFAULT '[]'::jsonb,
    regions_cibles JSONB NOT NULL DEFAULT '[]'::jsonb,
    types_marches_exclus JSONB DEFAULT '[]'::jsonb,
    montant_min_souhaite_mad NUMERIC(15, 2) DEFAULT 0.00,
    montant_max_souhaite_mad NUMERIC(15, 2) DEFAULT 100000000.00,
    taux_marge_cible_pct NUMERIC(5, 2) DEFAULT 18.00,
    tolerance_risque VARCHAR(20) DEFAULT 'MOYENNE',
    canaux_alertes JSONB DEFAULT '{"email": true, "telegram": false, "whatsapp": true}'::jsonb,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

