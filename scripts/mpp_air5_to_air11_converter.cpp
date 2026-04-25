// Mutation++-aware AIR-5 -> AIR-11 ASCII restart converter.
//
// Why this exists: 6 prior AIR-11 attempts all failed with "non-physical"
// cells because Mutation++ inverted (rho, E, E_ve) -> T and got T outside
// the [50K, 80000K] valid range. The energies were AIR-5-flavored, and
// Mutation++ AIR-11 interprets them with different conventions.
//
// This converter sidesteps the EOS mismatch by:
//   1. Reading AIR-5 ASCII restart for T_tr, T_ve, rho_i (PRIMITIVES are
//      already in the file)
//   2. Charge-balanced ion seeding (1e-9 mass per cation, electron derived
//      via charge neutrality)
//   3. Calling Mutation++ AIR-11 setState(rhos, [T_tr, T_ve], MODE_T) to
//      get an (E, E_ve) that is BY CONSTRUCTION self-consistent with
//      Mutation++ AIR-11 EOS at the given temperatures
//   4. Writing the AIR-11 restart with these self-consistent energies
//
// Compile on the VM:
//   g++ -std=c++17 -O2 \
//     -I/tmp/mutationpp-src/src \
//     -I/tmp/mutationpp-src/install/include/mutation++ \
//     mpp_air5_to_air11_converter.cpp \
//     -L/opt/su2-nemo/lib -lmutation__ \
//     -o /tmp/mpp_converter
//
// Run:
//   LD_LIBRARY_PATH=/opt/su2-nemo/lib MPP_DATA_DIRECTORY=/opt/su2-nemo/mpp-data \
//     /tmp/mpp_converter input.csv output.csv 1.0e-9
//
// AIR-11 species order (Mutation++ "air_11" mixture): determined by
// mix.speciesIndex() at runtime — DO NOT hardcode. We probe the mixture
// after construction and emit a debug line on first row.

#include <iostream>
#include <fstream>
#include <sstream>
#include <string>
#include <vector>
#include <map>
#include <cmath>
#include <cstdlib>
#include "mutation++.h"

using namespace std;
using namespace Mutation;

int main(int argc, char** argv) {
    if (argc != 4) {
        cerr << "Usage: " << argv[0] << " input.csv output.csv seed\n";
        return 1;
    }
    string inputPath = argv[1];
    string outputPath = argv[2];
    double seed = stod(argv[3]);

    // ── Initialize Mutation++ AIR-11 mixture ─────────────────────────────
    MixtureOptions opt("air_11");
    opt.setStateModel("ChemNonEqTTv");
    opt.setMechanism("none");  // we don't need chemistry rates here
    Mixture mix(opt);
    int nSpecies = mix.nSpecies();
    if (nSpecies != 11) {
        cerr << "ERROR: AIR-11 mixture has " << nSpecies
             << " species, expected 11\n";
        return 2;
    }

    // Build species index map by name (Mutation++ may reorder)
    map<string, int> idx;
    for (int i = 0; i < nSpecies; i++) {
        string name = mix.speciesName(i);
        idx[name] = i;
        cerr << "  species[" << i << "] = " << name << " M="
             << mix.speciesMw(i) * 1000 << " g/mol\n";
    }

    // We expect these names; map AIR-5 → AIR-11 indices through this lookup
    auto need = [&](const string& n) -> int {
        if (!idx.count(n)) {
            cerr << "ERROR: species " << n << " not in mixture (Mutation++ "
                 << "naming differs?). Names available: ";
            for (auto& p : idx) cerr << p.first << " ";
            cerr << "\n";
            exit(3);
        }
        return idx[n];
    };
    int ie  = need("e-");
    int iNp = need("N+");
    int iOp = need("O+");
    int iNOp = need("NO+");
    int iN2p = need("N2+");
    int iO2p = need("O2+");
    int iN  = need("N");
    int iO  = need("O");
    int iNO = need("NO");
    int iN2 = need("N2");
    int iO2 = need("O2");

    double M_e = mix.speciesMw(ie);
    double M_Np = mix.speciesMw(iNp);
    double M_Op = mix.speciesMw(iOp);
    double M_NOp = mix.speciesMw(iNOp);
    double M_N2p = mix.speciesMw(iN2p);
    double M_O2p = mix.speciesMw(iO2p);
    double e_per_unit_cation = M_e * (1.0 / M_Np + 1.0 / M_Op + 1.0 / M_NOp +
                                       1.0 / M_N2p + 1.0 / M_O2p);

    cerr << "  Charge-balance ratio rho_e/(seed*rho) = "
         << e_per_unit_cation << "\n";

    // ── Open input AIR-5 ASCII restart ────────────────────────────────────
    ifstream in(inputPath);
    if (!in) { cerr << "ERROR: can't open " << inputPath << "\n"; return 4; }

    string headerLine;
    getline(in, headerLine);
    vector<string> header;
    {
        stringstream ss(headerLine);
        string field;
        while (getline(ss, field, ',')) {
            // strip whitespace and quotes
            while (!field.empty() && (field.front() == ' ' || field.front() == '"'))
                field.erase(0, 1);
            while (!field.empty() && (field.back() == ' ' || field.back() == '"'))
                field.pop_back();
            header.push_back(field);
        }
    }

    auto col = [&](const string& name) -> int {
        for (int i = 0; i < (int)header.size(); i++)
            if (header[i] == name) return i;
        cerr << "ERROR: input missing column " << name << "\n";
        exit(5);
    };
    int cD0 = col("Density_0");  // AIR-5 N2
    int cD1 = col("Density_1");  // AIR-5 O2
    int cD2 = col("Density_2");  // AIR-5 NO
    int cD3 = col("Density_3");  // AIR-5 N
    int cD4 = col("Density_4");  // AIR-5 O
    int cMx = col("Momentum_x");
    int cMy = col("Momentum_y");
    int cMz = col("Momentum_z");
    int cTt = col("Temperature_tr");
    int cTv = col("Temperature_ve");
    bool hasPointID = (header[0] == "PointID" || header[0] == "pointid");
    int cX = hasPointID ? 1 : 0;
    int cY = cX + 1;
    int cZ = cX + 2;

    // ── Open output AIR-11 ASCII restart ──────────────────────────────────
    ofstream out(outputPath);
    if (!out) { cerr << "ERROR: can't open " << outputPath << "\n"; return 6; }

    // Build new header (AIR-11 ordering matches Mutation++'s species order)
    vector<string> newHeader;
    if (hasPointID) newHeader.push_back("PointID");
    newHeader.push_back("x");
    newHeader.push_back("y");
    newHeader.push_back("z");
    for (int i = 0; i < 11; i++) newHeader.push_back("Density_" + to_string(i));
    newHeader.push_back("Momentum_x");
    newHeader.push_back("Momentum_y");
    newHeader.push_back("Momentum_z");
    newHeader.push_back("Energy");
    newHeader.push_back("Energy_ve");
    for (size_t i = 0; i < newHeader.size(); i++) {
        out << "\"" << newHeader[i] << "\"" << (i + 1 < newHeader.size() ? "," : "\n");
    }

    // ── Per-cell loop ─────────────────────────────────────────────────────
    long nProcessed = 0, nDropped = 0;
    vector<double> rhos(nSpecies);
    vector<double> Ts(2);

    string line;
    while (getline(in, line)) {
        if (line.empty()) continue;
        vector<string> tok;
        {
            stringstream ss(line);
            string f;
            while (getline(ss, f, ',')) tok.push_back(f);
        }
        try {
            double rho_n2 = stod(tok[cD0]);
            double rho_o2 = stod(tok[cD1]);
            double rho_no = stod(tok[cD2]);
            double rho_N  = stod(tok[cD3]);
            double rho_O  = stod(tok[cD4]);
            double mx = stod(tok[cMx]);
            double my = stod(tok[cMy]);
            double mz = stod(tok[cMz]);
            double T_tr = stod(tok[cTt]);
            double T_ve = stod(tok[cTv]);

            double rho = rho_n2 + rho_o2 + rho_no + rho_N + rho_O;
            if (rho <= 0) { nDropped++; continue; }

            // Trace ion seeding (charge-balanced)
            double rho_cation = seed * rho;
            double rho_e = rho_cation * e_per_unit_cation;
            double ion_total_mass = 5 * rho_cation + rho_e;
            double f_n2 = (rho_n2 + rho_o2 > 0) ? rho_n2 / (rho_n2 + rho_o2) : 0.5;
            double f_o2 = 1.0 - f_n2;
            double new_rho_n2 = max(rho_n2 - ion_total_mass * f_n2, 1e-30 * rho);
            double new_rho_o2 = max(rho_o2 - ion_total_mass * f_o2, 1e-30 * rho);

            // Build species mass density vector in Mutation++ ordering
            for (int i = 0; i < nSpecies; i++) rhos[i] = 1e-30 * rho;  // floor
            rhos[ie]   = rho_e;
            rhos[iNp]  = rho_cation;
            rhos[iOp]  = rho_cation;
            rhos[iNOp] = rho_cation;
            rhos[iN2p] = rho_cation;
            rhos[iO2p] = rho_cation;
            rhos[iN]   = max(rho_N,  1e-30 * rho);
            rhos[iO]   = max(rho_O,  1e-30 * rho);
            rhos[iNO]  = max(rho_no, 1e-30 * rho);
            rhos[iN2]  = new_rho_n2;
            rhos[iO2]  = new_rho_o2;

            // Set state via T input. Mutation++ setState mode 1 = (rhos, Ts).
            Ts[0] = T_tr;
            Ts[1] = T_ve;
            mix.setState(rhos.data(), Ts.data(), 1);

            // Mutation++-self-consistent energies (volumetric J/m^3).
            // mixtureEnergies fills array: [E_total_mass*sum_rho, E_ve_mass*sum_rho]
            // for ChemNonEqTTv state model.
            double energies[2];
            mix.mixtureEnergies(energies);
            double E_internal = energies[0];   // total internal volumetric
            double E_ve = energies[1];         // V-E mode volumetric
            double v2 = (mx * mx + my * my + mz * mz) / (rho * rho);
            double E_total = E_internal + 0.5 * rho * v2;

            // Write output row
            if (hasPointID) out << tok[0] << ",";
            out << tok[cX] << "," << tok[cY] << "," << tok[cZ];
            for (int i = 0; i < nSpecies; i++) {
                char buf[32];
                snprintf(buf, sizeof(buf), ",%.16e", rhos[i]);
                out << buf;
            }
            char buf[32];
            snprintf(buf, sizeof(buf), ",%.16e,%.16e,%.16e,%.16e,%.16e\n",
                     mx, my, mz, E_total, E_ve);
            out << buf;
            nProcessed++;

            if (nProcessed == 1) {
                cerr << "First row: T_tr=" << T_tr << "K T_ve=" << T_ve
                     << "K rho=" << rho << " E_total=" << E_total
                     << " E_ve=" << E_ve << "\n";
            }
        } catch (...) {
            nDropped++;
        }
    }

    cerr << "Processed: " << nProcessed << " cells, dropped: "
         << nDropped << "\n";
    return 0;
}
